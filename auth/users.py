"""User lookup and password verification against the SQLite auth DB."""
import bcrypt
from auth.db import get_connection, init_db


def get_user(username: str) -> dict | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, agent_id, is_active "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row:
        return None
    return {
        "id":            row["id"],
        "username":      row["username"],
        "password_hash": row["password_hash"],
        "role":          row["role"],
        "agent_id":      row["agent_id"],
        "is_active":     bool(row["is_active"]),
    }


def verify_password(username: str, password: str) -> dict | None:
    """Return user dict if credentials are valid and account is active, else None."""
    user = get_user(username)
    if not user or not user["is_active"]:
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return {k: v for k, v in user.items() if k != "password_hash"}
    return None
