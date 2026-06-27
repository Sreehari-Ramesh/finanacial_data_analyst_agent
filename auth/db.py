"""SQLite database for auth — separate from the main SQL Server DB."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "users.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """Create the users table if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL DEFAULT 'agent',
                agent_id      INTEGER,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
