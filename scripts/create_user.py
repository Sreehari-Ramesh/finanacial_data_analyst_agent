"""CLI to create or update users in the SQLite auth database.

Usage:
    python scripts/create_user.py

Run from the project root. Prompts for username, password, and role.
Re-running with the same username updates that user's password / role.
"""
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bcrypt
from auth.db import get_connection, init_db


def main():
    init_db()
    print("=== SQL Q&A — Create / Update User ===\n")

    username = input("Username: ").strip()
    if not username:
        print("Error: username cannot be empty.")
        sys.exit(1)

    password = getpass.getpass("Password (min 6 chars): ")
    if len(password) < 6:
        print("Error: password must be at least 6 characters.")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match.")
        sys.exit(1)

    role = input("Role — admin / user [user]: ").strip().lower() or "user"
    if role not in ("admin", "user"):
        print("Error: role must be 'admin' or 'user'.")
        sys.exit(1)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                role          = excluded.role
            """,
            (username, password_hash, role),
        )
        conn.commit()

    print(f"\nUser '{username}' ({role}) saved successfully.")


if __name__ == "__main__":
    main()
