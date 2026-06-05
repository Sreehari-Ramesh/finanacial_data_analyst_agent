"""SQL Server connection test and table discovery."""
from sqlalchemy import text


def test_connection() -> dict:
    """Probe the SQL Server connection and return available table names.

    Returns:
        {"success": True,  "tables": [...], "server": "...", "database": "..."}
        {"success": False, "error": "..."}
    """
    try:
        from config import get_db_engine, DB_SERVER, DB_NAME
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))          # basic ping
        from database.schema import get_all_table_names
        tables = get_all_table_names()
        return {
            "success":  True,
            "tables":   tables,
            "server":   DB_SERVER,
            "database": DB_NAME,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
