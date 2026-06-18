"""Add retrieval freshness timestamp to normalized news events."""

from __future__ import annotations

import sqlite3


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def run(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "news_events", "last_seen_at"):
        conn.execute("ALTER TABLE news_events ADD COLUMN last_seen_at TEXT")
    conn.execute("UPDATE news_events SET last_seen_at = observed_at")
