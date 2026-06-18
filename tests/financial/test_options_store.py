from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from trader.options.models import OptionQuote, VolatilityHistoryRow
from trader.storage.migrations import latest_version
from trader.storage.store import Store


def _quote(
    trade_date: date,
    *,
    ticker: str = "SPY",
    expiration: date = date(2026, 6, 26),
    strike: float = 560.0,
    call_put: str = "Put",
    bid: float = 1.2,
    ask: float = 1.3,
    delta: float = -0.16,
) -> OptionQuote:
    return OptionQuote(
        trade_date=trade_date,
        ticker=ticker,
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        implied_vol=0.18,
        delta=delta,
        gamma=0.01,
        theta=-0.02,
        vega=0.15,
        rho=-0.01,
    )


def test_options_migration_creates_chain_and_backtest_tables(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"

    Store(db_path)

    assert latest_version() == 8
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'option_%' OR name LIKE 'iron_condor_%'"
            )
        }
    assert {
        "option_chain_eod",
        "option_volatility_history",
        "iron_condor_backtest_runs",
        "iron_condor_trades",
        "iron_condor_daily_marks",
    }.issubset(tables)


def test_upsert_and_read_option_chain_eod_sorted_and_filtered(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    written = store.upsert_option_chain_eod(
        "SPY",
        [
            _quote(date(2026, 5, 23), strike=565.0),
            _quote(date(2026, 5, 22), strike=560.0),
            _quote(date(2026, 5, 24), strike=570.0),
        ],
    )

    rows = store.get_option_chain_eod("SPY", since="2026-05-22", until="2026-05-23")
    assert written == 3
    assert [(row.trade_date.isoformat(), row.strike) for row in rows] == [
        ("2026-05-22", 560.0),
        ("2026-05-23", 565.0),
    ]


def test_upsert_option_chain_eod_overwrites_existing_quote(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.upsert_option_chain_eod("SPY", [_quote(date(2026, 5, 22), bid=1.2, ask=1.3)])

    store.upsert_option_chain_eod("SPY", [_quote(date(2026, 5, 22), bid=1.4, ask=1.5)])

    row = store.get_option_chain_eod("SPY")[0]
    assert row.bid == 1.4
    assert row.ask == 1.5


def test_upsert_and_read_option_volatility_history(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    rows = [
        VolatilityHistoryRow(
            trade_date=date(2026, 5, 22),
            ticker="SPY",
            hv_current=0.11,
            iv_current=0.14,
            iv_year_high=0.26,
            iv_year_low=0.10,
        )
    ]

    written = store.upsert_option_volatility_history("SPY", rows)

    assert written == 1
    stored = store.get_option_volatility_history("SPY")
    assert stored == rows
