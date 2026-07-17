"""Per-user conversation persistence — sessions and messages."""
from datetime import datetime, date
from auth.db import get_connection, init_db


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(user_id: int) -> int:
    """Create a new session and return its id."""
    init_db()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (user_id, title) VALUES (?, 'New conversation')",
            (user_id,),
        )
        conn.commit()
        return cur.lastrowid


def update_session_title(session_id: int, title: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
            (title, session_id),
        )
        conn.commit()


def get_sessions(user_id: int) -> list[dict]:
    """Return all sessions for the user, newest first."""
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM   sessions
            WHERE  user_id = ?
            ORDER  BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id":         row["id"],
            "title":      row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def delete_session(session_id: int, user_id: int) -> None:
    """Delete a session and all its messages."""
    init_db()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM conversations WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        conn.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Message management
# ---------------------------------------------------------------------------

def save_message(
    user_id: int,
    session_id: int,
    role: str,
    content: str,
    sql_query: str | None = None,
) -> None:
    """Save a message and bump the session's updated_at timestamp."""
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO conversations (user_id, session_id, role, content, sql_query)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, session_id, role, content or "", sql_query),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?",
            (session_id,),
        )
        conn.commit()


def load_session_messages(session_id: int) -> list[dict]:
    """Return all messages for a session in chronological order."""
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content, sql_query, created_at
            FROM   conversations
            WHERE  session_id = ?
            ORDER  BY id ASC
            """,
            (session_id,),
        ).fetchall()
    return [
        {
            "role":        row["role"],
            "content":     row["content"],
            "sql_query":   row["sql_query"],
            "created_at":  row["created_at"],
            "_historical": True,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Date grouping helper for sidebar
# ---------------------------------------------------------------------------

def date_group(dt_str: str) -> str:
    """Return a sidebar section label for a UTC datetime string."""
    try:
        dt = datetime.fromisoformat(dt_str).date()
    except Exception:
        return "Older"
    diff = (date.today() - dt).days
    if diff == 0:
        return "Today"
    if diff == 1:
        return "Yesterday"
    if diff <= 7:
        return "This week"
    if diff <= 30:
        return "This month"
    return datetime.fromisoformat(dt_str).strftime("%B %Y")
