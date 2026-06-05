"""Safe SQL execution utilities."""
import re
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from config import get_db_engine

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|PRAGMA)\b",
    re.IGNORECASE,
)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = get_db_engine()
    return _engine


def is_safe_sql(sql: str) -> bool:
    """Return False if the query contains any write/DDL keywords."""
    return not bool(_FORBIDDEN.search(sql))


def execute_query(sql: str) -> dict:
    """Execute a SELECT query and return structured results.

    Returns:
        {
            "success": bool,
            "columns": list[str],
            "rows": list[dict],
            "row_count": int,
            "error": str | None,
        }
    """
    sql = sql.strip().rstrip(";")

    if not is_safe_sql(sql):
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": "Unsafe SQL detected: only SELECT queries are permitted.",
        }

    try:
        with _get_engine().connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows    = [dict(zip(columns, row)) for row in result.fetchall()]
            return {
                "success":   True,
                "columns":   columns,
                "rows":      rows,
                "row_count": len(rows),
                "error":     None,
            }
    except SQLAlchemyError as exc:
        return {
            "success":   False,
            "columns":   [],
            "rows":      [],
            "row_count": 0,
            "error":     str(exc),
        }
    except Exception as exc:
        return {
            "success":   False,
            "columns":   [],
            "rows":      [],
            "row_count": 0,
            "error":     f"Unexpected error: {exc}",
        }
