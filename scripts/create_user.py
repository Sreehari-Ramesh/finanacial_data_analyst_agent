"""CLI to create or update users in the SQLite auth database.

Usage:
    python scripts/create_user.py

Run from the project root. Prompts for username, password, role, and agent ID.
Re-running with the same username updates that user's password / role / agent_id.
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

    role = input("Role — admin / agent [agent]: ").strip().lower() or "agent"
    if role not in ("admin", "agent"):
        print("Error: role must be 'admin' or 'agent'.")
        sys.exit(1)

    agent_id = None
    if role == "agent":
        raw = input("Agent ID (integer from the platform DB): ").strip()
        try:
            agent_id = int(raw)
        except ValueError:
            print("Error: agent ID must be an integer.")
            sys.exit(1)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, agent_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                role          = excluded.role,
                agent_id      = excluded.agent_id
            """,
            (username, password_hash, role, agent_id),
        )
        conn.commit()

    print(f"\nUser '{username}' ({role}) saved successfully.")
    if role == "agent":
        print(f"Agent ID: {agent_id}")


if __name__ == "__main__":
    main()
