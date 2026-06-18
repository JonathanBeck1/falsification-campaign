"""Attach point-in-time underlying spot to intraday option quote bars."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(option_quote_bars_1m)").fetchall()}
    if "underlying_price" not in columns:
        conn.execute("ALTER TABLE option_quote_bars_1m ADD COLUMN underlying_price REAL")
