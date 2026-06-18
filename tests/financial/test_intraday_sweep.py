from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import trader.options.intraday_sweep as intraday_sweep
from trader.options.greeks import black_scholes_price
from trader.options.intraday_sweep import format_intraday_iron_condor_sweep_report, run_intraday_iron_condor_sweep
from trader.options.models import OptionQuoteBar


def _bar(
    timestamp: datetime,
    strike: float,
    call_put: str,
    bid: float,
    ask: float,
    *,
    underlying_price: float = 100.0,
    expiration: date = date(2026, 6, 26),
) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker="SPY",
        expiration=expiration,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        underlying_price=underlying_price,
        source="unit-test",
    )


def _priced_bar(timestamp: datetime, strike: float, call_put: str, *, spot: float = 100.0) -> OptionQuoteBar:
    expiration = date(2026, 6, 26)
    mid = black_scholes_price(
        option_type=call_put,
        spot=spot,
        strike=strike,
        years_to_expiration=(expiration - timestamp.date()).days / 365,
        volatility=0.25,
        risk_free_rate=0.04,
    )
    return _bar(timestamp, strike, call_put, max(mid - 0.02, 0.01), mid + 0.02, underlying_price=spot)


def _two_timestamp_quotes() -> list[OptionQuoteBar]:
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    return [
        _priced_bar(entry_ts, 83, "Put"),
        _priced_bar(entry_ts, 88, "Put"),
        _priced_bar(entry_ts, 93, "Put"),
        _priced_bar(entry_ts, 107, "Call"),
        _priced_bar(entry_ts, 112, "Call"),
        _priced_bar(entry_ts, 117, "Call"),
        _bar(exit_ts, 88, "Put", 0.05, 0.08),
        _bar(exit_ts, 93, "Put", 0.20, 0.23),
        _bar(exit_ts, 107, "Call", 0.05, 0.08),
        _bar(exit_ts, 112, "Call", 0.01, 0.02),
    ]


def test_run_intraday_iron_condor_sweep_returns_ranked_rows():
    rows = run_intraday_iron_condor_sweep(
        _two_timestamp_quotes(),
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        entry_times=["09:45:00"],
        selection_mode="delta",
        wing_widths=[5.0],
        target_deltas=[0.16, 0.22],
        profit_targets=[0.50],
        stop_loss_multiples=[2.0],
    )

    assert len(rows) == 2
    assert [row.rank for row in rows] == [1, 2]
    assert {row.target_delta for row in rows} == {0.16, 0.22}
    assert rows[0].trade_count >= 1


def test_format_intraday_iron_condor_sweep_report_renders_ranked_table():
    rows = run_intraday_iron_condor_sweep(
        _two_timestamp_quotes(),
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        entry_times=["09:45:00"],
        selection_mode="delta",
        wing_widths=[5.0],
        target_deltas=[0.16],
        profit_targets=[0.50],
        stop_loss_multiples=[2.0],
    )

    report = format_intraday_iron_condor_sweep_report(rows, ticker="SPY")

    assert "# SPY Intraday Iron Condor Parameter Sweep" in report
    assert "| rank | entry_time | mode | wing | delta | short_bid |" in report
    assert "| 1 | 09:45:00 | delta | 5.00 | 0.16 |" in report


def test_run_intraday_iron_condor_sweep_ranks_no_trade_rows_after_real_trade_rows():
    eastern = ZoneInfo("America/New_York")
    entry_ts = datetime(2026, 5, 22, 9, 45, tzinfo=eastern)
    exit_ts = datetime(2026, 5, 22, 10, 15, tzinfo=eastern)
    losing_quotes = [
        _priced_bar(entry_ts, 83, "Put"),
        _priced_bar(entry_ts, 88, "Put"),
        _priced_bar(entry_ts, 93, "Put"),
        _priced_bar(entry_ts, 107, "Call"),
        _priced_bar(entry_ts, 112, "Call"),
        _priced_bar(entry_ts, 117, "Call"),
        _bar(exit_ts, 88, "Put", 0.01, 0.02),
        _bar(exit_ts, 93, "Put", 2.00, 2.20),
        _bar(exit_ts, 107, "Call", 2.00, 2.20),
        _bar(exit_ts, 112, "Call", 0.01, 0.02),
    ]

    rows = run_intraday_iron_condor_sweep(
        losing_quotes,
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        entry_times=["09:45:00"],
        selection_mode="delta",
        wing_widths=[5.0, 50.0],
        target_deltas=[0.16],
        profit_targets=[0.50],
        stop_loss_multiples=[2.0],
        max_wing_width=50.0,
    )

    assert rows[0].trade_count > 0
    assert rows[-1].trade_count == 0


def test_run_intraday_iron_condor_sweep_builds_replay_data_once(monkeypatch):
    calls = 0
    real_builder = intraday_sweep.build_intraday_quote_replay_data

    def spy_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(intraday_sweep, "build_intraday_quote_replay_data", spy_builder)

    rows = run_intraday_iron_condor_sweep(
        _two_timestamp_quotes(),
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        entry_times=["09:45:00"],
        selection_mode="delta",
        wing_widths=[5.0],
        target_deltas=[0.16, 0.22],
        profit_targets=[0.50, 0.75],
        stop_loss_multiples=[2.0],
    )

    assert calls == 1
    assert len(rows) == 4
