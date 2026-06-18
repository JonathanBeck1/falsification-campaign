"""Historical OHLCV + macro bars for the replay harness."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_bars (
            ticker             TEXT NOT NULL,
            trade_date         TEXT NOT NULL,
            open               REAL NOT NULL,
            high               REAL NOT NULL,
            low                REAL NOT NULL,
            close              REAL NOT NULL,
            volume             REAL NOT NULL DEFAULT 0,
            vix_close          REAL,
            yield_curve_10y_2y REAL,
            created_at         TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, trade_date)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_historical_bars_date ON historical_bars(trade_date)")
