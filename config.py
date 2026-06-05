import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL as SAUrl, Engine

load_dotenv()

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── SQL Server ────────────────────────────────────────────────────────────────
DB_SERVER      = os.getenv("DB_SERVER", "localhost")
DB_PORT        = int(os.getenv("DB_PORT", "1433"))
DB_NAME        = os.getenv("DB_NAME", "")
DB_USERNAME    = os.getenv("DB_USERNAME", "")
DB_PASSWORD    = os.getenv("DB_PASSWORD", "")
DB_DRIVER      = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_WINDOWS_AUTH = os.getenv("DB_WINDOWS_AUTH", "false").lower() == "true"

# ── Misc ──────────────────────────────────────────────────────────────────────
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
REPORTS_DIR.mkdir(exist_ok=True)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# ── Schema index (vector-based pruning) ──────────────────────────────────────
SCHEMA_INDEX_DIR = Path(os.getenv("SCHEMA_INDEX_DIR", "schema_index"))

# Hard ceiling — never inject more than this many tables regardless of query type
SCHEMA_MAX_TABLES = int(os.getenv("SCHEMA_MAX_TABLES", "8"))

# Cosine similarity threshold (0–1). Tables scoring below this are dropped.
# Raise toward 0.4 for tighter pruning; lower toward 0.15 for broader recall.
SCHEMA_SCORE_THRESHOLD = float(os.getenv("SCHEMA_SCORE_THRESHOLD", "0.25"))

# Embedding backend: "huggingface" (free, local) or "openai" (requires key)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")


def get_db_engine() -> Engine:
    """Build and return a SQLAlchemy engine for SQL Server.

    Supports both SQL Server Authentication and Windows Integrated Auth.
    Uses SQLAlchemy URL.create() so special characters in passwords are handled safely.
    """
    if not DB_NAME:
        raise ValueError(
            "DB_NAME is not set.\n"
            "Copy .env.example to .env and set your SQL Server database name."
        )

    common_query = {
        "driver": DB_DRIVER,
        "TrustServerCertificate": "yes",  # avoids SSL cert errors on local instances
    }

    if DB_WINDOWS_AUTH:
        url = SAUrl.create(
            "mssql+pyodbc",
            host=DB_SERVER,
            port=DB_PORT,
            database=DB_NAME,
            query={**common_query, "trusted_connection": "yes"},
        )
    else:
        if not DB_USERNAME:
            raise ValueError(
                "DB_USERNAME is not set. "
                "Either set DB_USERNAME/DB_PASSWORD or set DB_WINDOWS_AUTH=true."
            )
        url = SAUrl.create(
            "mssql+pyodbc",
            username=DB_USERNAME,
            password=DB_PASSWORD,
            host=DB_SERVER,
            port=DB_PORT,
            database=DB_NAME,
            query=common_query,
        )

    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def get_llm(temperature: float = 0):
    """Return the configured LLM instance."""
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set.\n"
                "Copy .env.example to .env and add your API key."
            )
        return ChatAnthropic(
            model=ANTHROPIC_MODEL,
            temperature=temperature,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=4096,
        )
    elif LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        if not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set.\n"
                "Copy .env.example to .env and add your API key."
            )
        return ChatOpenAI(
            model=OPENAI_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
        )
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use 'anthropic' or 'openai'."
        )
