"""Utilities for retrieving SQL Server schema info to feed into LLM prompts."""
from langchain_community.utilities import SQLDatabase
from config import get_db_engine

_db_instance = None


def get_db() -> SQLDatabase:
    """Return a cached SQLDatabase instance backed by the SQL Server engine."""
    global _db_instance
    if _db_instance is None:
        engine = get_db_engine()
        _db_instance = SQLDatabase(
            engine,
            sample_rows_in_table_info=3,
            lazy_table_reflection=True,   # avoids loading every table on startup
        )
    return _db_instance


def get_all_table_names() -> list[str]:
    """Return all user table names from the connected database."""
    return get_db().get_usable_table_names()


def get_schema(table_names: list[str] | None = None) -> str:
    """Return CREATE TABLE statements + sample rows for the given tables.

    If table_names is None, returns schema for all tables.
    """
    db = get_db()
    if table_names:
        all_tables = get_all_table_names()
        valid = [t for t in table_names if t in all_tables]
        if not valid:
            valid = all_tables
        return db.get_table_info(table_names=valid)
    return db.get_table_info()


def get_table_descriptions() -> str:
    """Return a formatted list of available tables for the analysis prompt."""
    try:
        tables = get_all_table_names()
    except Exception:
        return "  (could not load tables — check database connection)"
    if not tables:
        return "  (no user tables found in the connected database)"
    return "\n".join(f"  - {t}" for t in tables)
