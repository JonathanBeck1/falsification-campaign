"""ThetaData-compatible intraday option quote bars and replay tables."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_quote_bars_1m (
            ticker        TEXT NOT NULL,
            quote_ts      TEXT NOT NULL,
            trade_date    TEXT NOT NULL,
            expiration    TEXT NOT NULL,
            strike        REAL NOT NULL,
            call_put      TEXT NOT NULL,
            bid           REAL,
            ask           REAL,
            bid_size      INTEGER,
            ask_size      INTEGER,
            bid_exchange  INTEGER,
            ask_exchange  INTEGER,
            bid_condition INTEGER,
            ask_condition INTEGER,
            source        TEXT NOT NULL DEFAULT 'thetadata',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, quote_ts, expiration, strike, call_put)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_option_quote_bars_1m_ticker_date
        ON option_quote_bars_1m(ticker, trade_date)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_option_quote_bars_1m_contract
        ON option_quote_bars_1m(ticker, expiration, strike, call_put)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iron_condor_intraday_backtest_runs (
            run_id       TEXT PRIMARY KEY,
            ticker       TEXT NOT NULL,
            started_at   TEXT NOT NULL DEFAULT (datetime('now')),
            start_date   TEXT,
            end_date     TEXT,
            entry_time   TEXT NOT NULL,
            params_json  TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iron_condor_intraday_trades (
            trade_id          TEXT PRIMARY KEY,
            run_id            TEXT NOT NULL REFERENCES iron_condor_intraday_backtest_runs(run_id) ON DELETE CASCADE,
            ticker            TEXT NOT NULL,
            entry_ts          TEXT NOT NULL,
            exit_ts           TEXT,
            expiration        TEXT NOT NULL,
            short_put_strike  REAL NOT NULL,
            long_put_strike   REAL NOT NULL,
            short_call_strike REAL NOT NULL,
            long_call_strike  REAL NOT NULL,
            entry_credit      REAL NOT NULL,
            exit_debit        REAL,
            max_risk          REAL NOT NULL,
            pnl               REAL,
            exit_reason       TEXT NOT NULL,
            holding_minutes   INTEGER NOT NULL,
            dte_entry         INTEGER NOT NULL,
            dte_exit          INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_iron_condor_intraday_trades_run
        ON iron_condor_intraday_trades(run_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iron_condor_intraday_marks (
            run_id     TEXT NOT NULL REFERENCES iron_condor_intraday_backtest_runs(run_id) ON DELETE CASCADE,
            trade_id   TEXT NOT NULL,
            mark_ts    TEXT NOT NULL,
            exit_debit REAL NOT NULL,
            pnl        REAL NOT NULL,
            dte        INTEGER NOT NULL,
            PRIMARY KEY (run_id, trade_id, mark_ts)
        )
        """
    )
