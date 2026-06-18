"""Resumable backfill ledger for ThetaData option-quote pulls."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_quote_backfill_ledger (
            ticker             TEXT NOT NULL,
            trade_date         TEXT NOT NULL,
            status             TEXT NOT NULL,
            expirations_pulled INTEGER NOT NULL DEFAULT 0,
            quote_rows         INTEGER NOT NULL DEFAULT 0,
            attempts           INTEGER NOT NULL DEFAULT 0,
            last_error         TEXT,
            updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, trade_date)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_option_quote_backfill_ledger_status "
        "ON option_quote_backfill_ledger(ticker, status)"
    )
