"""Add trade-level explainability fields to intraday option backtests."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(iron_condor_intraday_trades)").fetchall()}
    additions = {
        "short_put_delta": "REAL",
        "short_call_delta": "REAL",
        "max_favorable_pnl": "REAL",
        "max_adverse_pnl": "REAL",
        "mark_count": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, column_type in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE iron_condor_intraday_trades ADD COLUMN {name} {column_type}")
