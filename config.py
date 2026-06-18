from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL as SAUrl, Engine
import os

#---- LangSmith ---------------------------------
os.environ["LANGSMITH_API_KEY"] = "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"

os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = "qna_agent"


# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_PROVIDER      = "openai"
ANTHROPIC_API_KEY = "your_anthropic_api_key_here"
ANTHROPIC_MODEL   = "claude-sonnet-4-6"
OPENAI_API_KEY    = "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"
OPENAI_MODEL      = "gpt-5.4"

# ── SQL Server ────────────────────────────────────────────────────────────────
DB_SERVER       = "77.81.191.141"
DB_PORT         = 36773
DB_NAME         = "777AiReport"
DB_USERNAME     = "DBTester"
DB_PASSWORD     = "Lmno@753"
DB_DRIVER       = "ODBC Driver 17 for SQL Server"
DB_WINDOWS_AUTH = False

# ── Misc ──────────────────────────────────────────────────────────────────────
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)
MAX_RETRIES = 3

# ── Schema index (vector-based pruning) ──────────────────────────────────────
SCHEMA_INDEX_DIR = Path("schema_index")

# Hard ceiling — never inject more than this many tables regardless of query type
SCHEMA_MAX_TABLES = 8

# Cosine similarity threshold (0–1). Tables scoring below this are dropped.
# Raise toward 0.4 for tighter pruning; lower toward 0.15 for broader recall.
SCHEMA_SCORE_THRESHOLD = 0.25

# Embedding backend: "huggingface" (free, local) or "openai" (requires key)
EMBEDDING_PROVIDER = "huggingface"


def get_db_engine() -> Engine:
    """Build and return a SQLAlchemy engine for SQL Server.

    Supports both SQL Server Authentication and Windows Integrated Auth.
    Uses SQLAlchemy URL.create() so special characters in passwords are handled safely.
    """
    if not DB_NAME:
        raise ValueError("DB_NAME is not set. Set it in config.py.")

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
            raise ValueError("ANTHROPIC_API_KEY is not set. Set it in config.py.")
        return ChatAnthropic(
            model=ANTHROPIC_MODEL,
            temperature=temperature,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=4096,
        )
    elif LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set. Set it in config.py.")
        return ChatOpenAI(
            model=OPENAI_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
        )
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Use 'anthropic' or 'openai'."
        )
