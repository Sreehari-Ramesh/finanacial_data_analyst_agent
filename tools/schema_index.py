"""Schema pruning via FAISS vector index.

Pipeline
--------
  build()    — introspect DB → build rich metadata docs → embed → save FAISS to disk
  retrieve() — embed (question + intent) → cosine search → return top-k table names

The index is saved to SCHEMA_INDEX_DIR and is only rebuilt when the set of
tables in the database changes (detected by comparing a stored hash).
"""

import json
import hashlib
import warnings
from pathlib import Path
from typing import Optional

from sqlalchemy import inspect as sa_inspect, text
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

from config import SCHEMA_INDEX_DIR, SCHEMA_MAX_TABLES, SCHEMA_SCORE_THRESHOLD

# suppress noisy HuggingFace / tokeniser warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ── Platform context hints ────────────────────────────────────────────────────

def _load_table_hints() -> dict[str, str]:
    """Parse platform_context.md and return a {table_name: description} dict."""
    ctx_file = Path(__file__).parent.parent / "platform_context.md"
    if not ctx_file.exists():
        return {}

    hints: dict[str, str] = {}
    current_table: str | None = None
    current_lines: list[str] = []

    for line in ctx_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            # Close the previous section
            if current_table:
                hints[current_table] = "\n".join(current_lines).strip()
            if line.startswith("### tbl"):
                current_table = line[4:].strip()   # "### tblClient" → "tblClient"
                current_lines = []
            else:
                current_table = None
                current_lines = []
        elif line.startswith("## "):
            if current_table:
                hints[current_table] = "\n".join(current_lines).strip()
                current_table = None
                current_lines = []
        elif current_table is not None:
            current_lines.append(line)

    if current_table and current_lines:
        hints[current_table] = "\n".join(current_lines).strip()

    return hints


_TABLE_HINTS: dict[str, str] = {}   # populated lazily on first build


def _get_table_hints() -> dict[str, str]:
    global _TABLE_HINTS
    if not _TABLE_HINTS:
        _TABLE_HINTS = _load_table_hints()
    return _TABLE_HINTS


# ── Embedding factory ─────────────────────────────────────────────────────────

def _make_embeddings():
    """Return the configured embedding model (cached per process)."""
    # if EMBEDDING_PROVIDER == "openai" and OPENAI_API_KEY:
    #     from langchain_openai import OpenAIEmbeddings
    #     return OpenAIEmbeddings(
    #         model="text-embedding-3-small",
    #         api_key=OPENAI_API_KEY,
    #     )
    # Default: local sentence-transformers (no API key required)
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


# ── Metadata extraction ───────────────────────────────────────────────────────

def _extract_metadata(engine) -> list[dict]:
    """Return a list of table-metadata dicts using SQLAlchemy inspector.

    Each dict:
        name          str
        columns       list[str]   — "col_name (TYPE) [PK] → ref_table.ref_col"
        sample_values list[str]   — "col: val1, val2" for low-cardinality text cols
        row_count     int
    """
    inspector = sa_inspect(engine)
    table_names = inspector.get_table_names()
    metadata = []

    for tbl in table_names:
        # ── Columns ──────────────────────────────────────────────────────────
        pk_cols = set(
            inspector.get_pk_constraint(tbl).get("constrained_columns", [])
        )
        fk_lookup: dict[str, str] = {}
        for fk in inspector.get_foreign_keys(tbl):
            for local, ref in zip(
                fk["constrained_columns"], fk["referred_columns"]
            ):
                fk_lookup[local] = f"{fk['referred_table']}.{ref}"

        col_lines = []
        text_cols = []
        for col in inspector.get_columns(tbl):
            name   = col["name"]
            dtype  = str(col["type"])
            parts  = [f"{name} ({dtype})"]
            if name in pk_cols:
                parts.append("[PK]")
            if name in fk_lookup:
                parts.append(f"→ {fk_lookup[name]}")
            col_lines.append(" ".join(parts))
            if any(k in dtype.lower() for k in ("char", "text", "nvar", "var")):
                text_cols.append(name)

        # ── Sample / distinct values for text columns ─────────────────────
        sample_lines = []
        with engine.connect() as conn:
            for col_name in text_cols[:6]:          # cap at 6 columns
                try:
                    rows = conn.execute(
                        text(
                            f"SELECT DISTINCT TOP 6 [{col_name}] "
                            f"FROM [{tbl}] WHERE [{col_name}] IS NOT NULL"
                        )
                    ).fetchall()
                    vals = [str(r[0]) for r in rows if r[0] is not None]
                    if vals:
                        sample_lines.append(f"{col_name}: {', '.join(vals)}")
                except Exception:
                    pass

            # ── Row count ─────────────────────────────────────────────────
            try:
                row_count = conn.execute(
                    text(f"SELECT COUNT(*) FROM [{tbl}]")
                ).scalar() or 0
            except Exception:
                row_count = 0

        metadata.append({
            "name":          tbl,
            "columns":       col_lines,
            "sample_values": sample_lines,
            "row_count":     row_count,
        })

    return metadata


# ── Document builder ──────────────────────────────────────────────────────────

_KEYWORD_MAP = {
    ("date", "time", "created", "updated", "timestamp"):
        ["date", "time", "period", "when", "history", "trend"],
    ("amount", "total", "price", "cost", "revenue", "salary", "balance", "fee"):
        ["money", "financial", "revenue", "payment", "cost"],
    ("name", "email", "phone", "address", "contact"):
        ["person", "contact", "user", "customer", "identity"],
    ("status", "state", "type", "category", "segment"):
        ["classification", "group", "filter", "kind"],
    ("count", "quantity", "qty", "stock", "inventory"):
        ["quantity", "volume", "stock", "how many"],
    ("id", "key", "ref", "code"):
        ["identifier", "reference", "lookup"],
}


def _infer_keywords(col_lines: list[str]) -> list[str]:
    cols_lower = " ".join(col_lines).lower()
    keywords: set[str] = set()
    for triggers, kws in _KEYWORD_MAP.items():
        if any(t in cols_lower for t in triggers):
            keywords.update(kws)
    return sorted(keywords)


def _build_document(meta: dict) -> Document:
    """Convert a table metadata dict into a rich text document for embedding."""
    lines = [
        f"Table: {meta['name']}",
        f"Rows: {meta['row_count']:,}",
        "",
        f"Columns ({len(meta['columns'])}):",
    ]
    lines.extend(f"  {c}" for c in meta["columns"])

    if meta["sample_values"]:
        lines.append("")
        lines.append("Sample values:")
        lines.extend(f"  {s}" for s in meta["sample_values"])

    kws = _infer_keywords(meta["columns"])
    if kws:
        lines.append("")
        lines.append(f"Concepts: {', '.join(kws)}")

    hint = _get_table_hints().get(meta["name"], "")
    if hint:
        lines.append("")
        lines.append("Platform context:")
        lines.extend(f"  {l}" for l in hint.splitlines() if l.strip())

    return Document(
        page_content="\n".join(lines),
        metadata={"table_name": meta["name"]},
    )


# ── Per-question-type table caps ──────────────────────────────────────────────

_TYPE_CAPS: dict[str, int] = {
    "simple_lookup": 2,   # single table, direct lookup
    "aggregation":   3,   # usually one table, occasionally two
    "comparison":    3,   # comparing across one or two dimensions
    "ranking":       3,   # top-N within a single domain
    "trend":         4,   # often needs a date + fact table
    "report":        6,   # multi-table joins expected
}


# ── Schema index ──────────────────────────────────────────────────────────────

class SchemaIndex:
    """FAISS-backed schema index for semantic table retrieval."""

    _FAISS_FOLDER = "faiss"
    _META_FILE    = "meta.json"

    def __init__(self, index_dir: Path = SCHEMA_INDEX_DIR):
        self.index_dir  = Path(index_dir)
        self._store: Optional[FAISS] = None
        self._embeddings = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _emb(self):
        if self._embeddings is None:
            self._embeddings = _make_embeddings()
        return self._embeddings

    def _faiss_path(self) -> Path:
        return self.index_dir / self._FAISS_FOLDER

    def _meta_path(self) -> Path:
        return self.index_dir / self._META_FILE

    @staticmethod
    def _tables_hash(table_names: list[str]) -> str:
        joined = ",".join(sorted(table_names))
        return hashlib.md5(joined.encode()).hexdigest()

    # ── Public API ────────────────────────────────────────────────────────────

    def needs_rebuild(self, engine) -> bool:
        """True if index doesn't exist or database tables have changed."""
        if not self._meta_path().exists():
            return True
        try:
            saved = json.loads(self._meta_path().read_text())
            current_tables = sa_inspect(engine).get_table_names()
            return saved.get("hash") != self._tables_hash(current_tables)
        except Exception:
            return True

    def build(self, engine) -> None:
        """Extract metadata, embed every table, persist FAISS index to disk."""
        self.index_dir.mkdir(parents=True, exist_ok=True)

        print("[schema_index] Extracting table metadata…")
        table_metas = _extract_metadata(engine)
        if not table_metas:
            raise RuntimeError("No user tables found — check DB_NAME in .env")

        print(f"[schema_index] Embedding {len(table_metas)} tables…")
        docs  = [_build_document(m) for m in table_metas]
        store = FAISS.from_documents(docs, self._emb())
        store.save_local(str(self._faiss_path()))

        meta = {
            "tables": [m["name"] for m in table_metas],
            "hash":   self._tables_hash([m["name"] for m in table_metas]),
            "count":  len(table_metas),
        }
        self._meta_path().write_text(json.dumps(meta, indent=2))
        self._store = store
        print(f"[schema_index] Index saved → {self.index_dir}  ({len(table_metas)} tables)")

    def load(self) -> None:
        """Load persisted FAISS index from disk."""
        self._store = FAISS.load_local(
            str(self._faiss_path()),
            self._emb(),
            allow_dangerous_deserialization=True,
        )

    def ensure_ready(self, engine) -> None:
        """Build or load the index, rebuilding only when schema has changed."""
        if self.needs_rebuild(engine):
            self.build(engine)
        elif self._store is None:
            self.load()

    def retrieve(
        self,
        query: str,
        question_type: str = "aggregation",
        hint_tables: list[str] | None = None,
    ) -> list[str]:
        """Return a dynamically-sized list of relevant table names.

        Table count is determined by two signals:
          1. question_type cap  — simple queries get fewer tables than reports
          2. score threshold    — tables below SCHEMA_SCORE_THRESHOLD are dropped

        hint_tables (from LLM analysis) are always included first regardless
        of their score; semantic retrieval fills the remaining slots.
        """
        if self._store is None:
            self.load()

        hints     = list(dict.fromkeys(hint_tables or []))
        hint_set  = set(hints)

        # Per-type ceiling — how many tables this kind of query warrants
        type_cap = _TYPE_CAPS.get(question_type, 4)
        # Never exceed the hard global maximum
        effective_cap = min(type_cap, SCHEMA_MAX_TABLES)

        # Over-fetch candidates, then filter by relevance score
        candidates = self._store.similarity_search_with_relevance_scores(
            query, k=SCHEMA_MAX_TABLES
        )
        semantic = [
            doc.metadata["table_name"]
            for doc, score in candidates
            if doc.metadata["table_name"] not in hint_set
            and score >= SCHEMA_SCORE_THRESHOLD
        ]

        # Fill remaining slots up to the effective cap (always leave at least 1)
        remaining = max(effective_cap - len(hints), 1)
        return list(dict.fromkeys(hints + semantic[:remaining]))


# ── Module-level singleton ────────────────────────────────────────────────────

_index: Optional[SchemaIndex] = None


def get_schema_index() -> SchemaIndex:
    global _index
    if _index is None:
        _index = SchemaIndex()
    return _index
