"""Cash-secured short-put backtest tests on tiny synthetic fixtures."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trader import cli
from trader.options.models import OptionQuoteBar
from trader.options.short_put import (
    ShortPutBacktestConfig,
    ShortPutSelectorConfig,
    run_short_put_backtest,
)
from trader.options.sources import SqliteQuoteSource
from trader.storage.store import Store

EASTERN = ZoneInfo("America/New_York")
EXPIRATION = date(2026, 6, 26)


def _bar(timestamp: datetime, strike: float, call_put: str, bid: float, ask: float) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker="SPY",
        expiration=EXPIRATION,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        underlying_price=585.0,
        bid_size=10,
        ask_size=10,
        bid_exchange=22,
        ask_exchange=73,
        bid_condition=50,
        ask_condition=50,
        source="unit-test",
    )


def _day_bars(trade_date: date) -> list[OptionQuoteBar]:
    entry_ts = datetime(trade_date.year, trade_date.month, trade_date.day, 9, 45, tzinfo=EASTERN)
    exit_ts = datetime(trade_date.year, trade_date.month, trade_date.day, 10, 15, tzinfo=EASTERN)
    return [
        _bar(entry_ts, 555, "Put", 0.50, 0.55),
        _bar(entry_ts, 560, "Put", 1.20, 1.30),  # target short put (bid ~ 1.20)
        _bar(exit_ts, 560, "Put", 0.55, 0.60),  # buy back at 0.60 -> profit target
    ]


def _config(start: date, end: date) -> ShortPutBacktestConfig:
    return ShortPutBacktestConfig(
        ticker="SPY",
        start=start,
        end=end,
        selector=ShortPutSelectorConfig(
            min_dte=30,
            max_dte=45,
            selection_mode="premium",
            target_short_bid=1.20,
            min_credit=0.05,
        ),
        entry_time="09:45:00",
        profit_target_pct=0.50,
        stop_loss_credit_multiple=2.0,
    )


def test_short_put_opens_and_hits_profit_target():
    d0 = date(2026, 5, 22)
    result = run_short_put_backtest(_day_bars(d0), _config(d0, d0))

    assert result.summary.trade_count == 1
    trade = result.trades[0]
    assert trade.strike == 560
    assert trade.entry_credit == 1.20
    assert trade.exit_debit == 0.60
    assert trade.exit_reason == "profit_target"
    # (credit - debit) * 100 = (1.20 - 0.60) * 100 = 60
    assert trade.pnl == 60.0
    assert trade.max_risk == round((560 - 1.20) * 100, 2)


def test_short_put_picks_bid_closest_to_target():
    d0 = date(2026, 5, 22)
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=EASTERN)
    bars = [
        _bar(entry_ts, 550, "Put", 0.30, 0.35),
        _bar(entry_ts, 555, "Put", 0.90, 0.95),
        _bar(entry_ts, 560, "Put", 1.20, 1.30),
    ]
    config = ShortPutBacktestConfig(
        ticker="SPY",
        start=d0,
        end=d0,
        selector=ShortPutSelectorConfig(min_dte=30, max_dte=45, selection_mode="premium", target_short_bid=0.90),
        entry_time="09:45:00",
    )
    result = run_short_put_backtest(bars, config)
    assert result.trades[0].strike == 555


def test_short_put_streams_identically_from_sqlite_source(tmp_path: Path):
    dates = [date(2026, 5, 22), date(2026, 5, 26)]
    store = Store(tmp_path / "trader.sqlite")
    for d in dates:
        store.upsert_option_quote_bars_1m("SPY", _day_bars(d))

    all_bars = [bar for d in dates for bar in _day_bars(d)]
    config = _config(dates[0], dates[-1])

    list_result = run_short_put_backtest(all_bars, config)
    source_result = run_short_put_backtest(SqliteQuoteSource(store), config)

    assert list_result.summary == source_result.summary
    assert source_result.summary.trade_count == 2
    assert [t.pnl for t in source_result.trades] == [t.pnl for t in list_result.trades]


def test_short_put_no_entry_when_below_min_credit():
    d0 = date(2026, 5, 22)
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=EASTERN)
    bars = [_bar(entry_ts, 560, "Put", 0.02, 0.04)]
    config = ShortPutBacktestConfig(
        ticker="SPY",
        start=d0,
        end=d0,
        selector=ShortPutSelectorConfig(min_dte=30, max_dte=45, selection_mode="premium", min_credit=0.05),
        entry_time="09:45:00",
    )
    result = run_short_put_backtest(bars, config)
    assert result.summary.opened_count == 0
    assert result.trades == []


def test_cli_options_backtest_short_put_writes_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output = tmp_path / "short-put.md"
    store = Store(db_path)
    d0 = date(2026, 5, 22)
    store.upsert_option_quote_bars_1m("SPY", _day_bars(d0))
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(sqlite_path=db_path, trader_live=False))

    rc = cli.main(
        [
            "options-backtest-short-put",
            "--ticker",
            "SPY",
            "--start",
            d0.isoformat(),
            "--end",
            d0.isoformat(),
            "--entry-time",
            "09:45:00",
            "--selection-mode",
            "premium",
            "--target-short-bid",
            "1.20",
            "--output",
            str(output),
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "Short put report written to" in out
    report = output.read_text()
    assert "# SPY Cash-Secured Short Put" in report
    assert "| total_pnl | 60.00 |" in report
    json_path = output.with_suffix(".json")
    assert json_path.exists()
    trades_md = output.with_name("short-put_trades.md")
    assert "profit_target" in trades_md.read_text()
