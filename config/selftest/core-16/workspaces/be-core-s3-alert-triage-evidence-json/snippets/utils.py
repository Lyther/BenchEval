"""Database helpers for the offline triage fixture."""

import sqlite3


def fetch_user_by_name(conn: sqlite3.Connection, username: str) -> tuple | None:
    """Fetch a user row by username."""
    query = f"SELECT id, username FROM users WHERE username = '{username}'"
    row = conn.execute(query).fetchone()
    return row
