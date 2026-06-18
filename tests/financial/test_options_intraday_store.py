from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trader.options.intraday import (
    IntradayIronCondorBacktestConfig,
    IntradayIronCondorBacktestResult,
    IntradayIronCondorBacktestSummary,
    IntradayIronCondorMark,
    IntradayIronCondorTrade,
)
from trader.options.models import OptionQuoteBar
from trader.storage.migrations import latest_version
from trader.storage.store import Store


def _quote_bar(
    timestamp: datetime,
    *,
    ticker: str = "SPY",
    expiration: str = "2026-06-26",
    strike: float = 560.0,
    call_put: str = "Put",
    bid: float | None = 1.2,
    ask: float | None = 1.3,
) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker=ticker,
        expiration=datetime.strptime(expiration, "%Y-%m-%d").date(),
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        underlying_price=586.12,
        bid_size=10,
        ask_size=12,
        bid_exchange=22,
        ask_exchange=73,
        bid_condition=50,
        ask_condition=50,
        source="thetadata",
    )


def test_options_intraday_migration_creates_quote_and_backtest_tables(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"

    Store(db_path)

    assert latest_version() == 8
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND (
                    name = 'option_quote_bars_1m'
                    OR name LIKE 'iron_condor_intraday_%'
                  )
                """
            )
        }
    assert {
        "option_quote_bars_1m",
        "iron_condor_intraday_backtest_runs",
        "iron_condor_intraday_trades",
        "iron_condor_intraday_marks",
    }.issubset(tables)


def test_upsert_and_read_option_quote_bars_1m_sorted_filtered_and_idempotent(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    eastern = ZoneInfo("America/New_York")
    t0 = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    t1 = datetime(2026, 5, 22, 9, 46, tzinfo=eastern)
    t2 = datetime(2026, 5, 23, 9, 45, tzinfo=eastern)

    written = store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _quote_bar(t1, strike=610.0, call_put="Call", bid=1.4, ask=1.5),
            _quote_bar(t0, strike=560.0, call_put="Put", bid=1.2, ask=1.3),
            _quote_bar(t2, strike=560.0, call_put="Put", bid=1.1, ask=1.2),
        ],
    )
    store.upsert_option_quote_bars_1m("SPY", [_quote_bar(t0, strike=560.0, call_put="Put", bid=1.25, ask=1.35)])

    rows = store.get_option_quote_bars_1m("SPY", trade_date="2026-05-22")

    assert written == 3
    assert [(row.timestamp.isoformat(), row.strike, row.call_put) for row in rows] == [
        ("2026-05-22T09:45:00-04:00", 560.0, "Put"),
        ("2026-05-22T09:46:00-04:00", 610.0, "Call"),
    ]
    assert rows[0].bid == 1.25
    assert rows[0].ask == 1.35
    assert rows[0].underlying_price == 586.12
    assert rows[0].trade_date.isoformat() == "2026-05-22"
    assert rows[0].dte == 35


def test_save_intraday_backtest_result_persists_trade_explainability(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    result = IntradayIronCondorBacktestResult(
        run_id="run-1",
        config=IntradayIronCondorBacktestConfig(ticker="SPY"),
        trades=[
            IntradayIronCondorTrade(
                trade_id="trade-1",
                ticker="SPY",
                entry_ts=entry_ts,
                exit_ts=exit_ts,
                expiration=datetime.strptime("2026-06-26", "%Y-%m-%d").date(),
                short_put_strike=560.0,
                long_put_strike=555.0,
                short_call_strike=610.0,
                long_call_strike=615.0,
                entry_credit=1.3,
                exit_debit=0.6,
                max_risk=3.7,
                pnl=70.0,
                exit_reason="profit_target",
                holding_minutes=30,
                dte_entry=35,
                dte_exit=35,
                short_put_delta=-0.16,
                short_call_delta=0.16,
                max_favorable_pnl=75.0,
                max_adverse_pnl=-25.0,
                mark_count=3,
            )
        ],
        marks=[
            IntradayIronCondorMark(
                trade_id="trade-1",
                mark_ts=exit_ts,
                exit_debit=0.6,
                pnl=70.0,
                dte=35,
            )
        ],
        summary=IntradayIronCondorBacktestSummary(
            opened_count=1,
            closed_count=1,
            unclosed_count=0,
            trade_count=1,
            win_rate=1.0,
            total_pnl=70.0,
            average_pnl=70.0,
            average_holding_minutes=30.0,
            max_drawdown=0.0,
            profit_factor=None,
        ),
    )

    store.save_intraday_iron_condor_backtest_result(result)

    with sqlite3.connect(tmp_path / "trader.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT short_put_delta, short_call_delta, max_favorable_pnl, max_adverse_pnl, mark_count
            FROM iron_condor_intraday_trades
            WHERE trade_id = 'trade-1'
            """
        ).fetchone()

    assert dict(row) == {
        "short_put_delta": -0.16,
        "short_call_delta": 0.16,
        "max_favorable_pnl": 75.0,
        "max_adverse_pnl": -25.0,
        "mark_count": 3,
    }
