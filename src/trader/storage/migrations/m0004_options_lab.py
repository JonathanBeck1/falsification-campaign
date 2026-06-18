"""Research-only options chain and iron-condor backtest tables."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_chain_eod (
            ticker       TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            expiration  TEXT NOT NULL,
            strike      REAL NOT NULL,
            call_put    TEXT NOT NULL,
            bid         REAL,
            ask         REAL,
            implied_vol REAL,
            delta       REAL,
            gamma       REAL,
            theta       REAL,
            vega        REAL,
            rho         REAL,
            source      TEXT NOT NULL DEFAULT 'dolthub_post_no_preference',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, trade_date, expiration, strike, call_put)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_chain_eod_ticker_date ON option_chain_eod(ticker, trade_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_option_chain_eod_expiration ON option_chain_eod(expiration)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS option_volatility_history (
            ticker        TEXT NOT NULL,
            trade_date    TEXT NOT NULL,
            hv_current    REAL,
            hv_week_ago   REAL,
            hv_month_ago  REAL,
            hv_year_high  REAL,
            hv_year_low   REAL,
            iv_current    REAL,
            iv_week_ago   REAL,
            iv_month_ago  REAL,
            iv_year_high  REAL,
            iv_year_low   REAL,
            source        TEXT NOT NULL DEFAULT 'dolthub_post_no_preference',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, trade_date)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_option_volatility_history_date ON option_volatility_history(trade_date)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iron_condor_backtest_runs (
            run_id      TEXT PRIMARY KEY,
            ticker      TEXT NOT NULL,
            started_at  TEXT NOT NULL DEFAULT (datetime('now')),
            start_date  TEXT,
            end_date    TEXT,
            params_json TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iron_condor_trades (
            trade_id          TEXT PRIMARY KEY,
            run_id            TEXT NOT NULL REFERENCES iron_condor_backtest_runs(run_id) ON DELETE CASCADE,
            ticker            TEXT NOT NULL,
            entry_date        TEXT NOT NULL,
            exit_date         TEXT,
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
            holding_days      INTEGER NOT NULL,
            dte_entry         INTEGER NOT NULL,
            dte_exit          INTEGER
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_iron_condor_trades_run ON iron_condor_trades(run_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iron_condor_daily_marks (
            run_id     TEXT NOT NULL REFERENCES iron_condor_backtest_runs(run_id) ON DELETE CASCADE,
            trade_id   TEXT NOT NULL,
            mark_date  TEXT NOT NULL,
            exit_debit REAL NOT NULL,
            pnl        REAL NOT NULL,
            dte        INTEGER NOT NULL,
            PRIMARY KEY (run_id, trade_id, mark_date)
        )
        """
    )
