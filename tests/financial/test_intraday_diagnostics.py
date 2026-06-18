from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from trader.options.greeks import black_scholes_price
from trader.options.intraday import IntradayIronCondorSelectorConfig
from trader.options.intraday_diagnostics import diagnose_intraday_selection, format_intraday_selection_report
from trader.options.models import OptionQuoteBar


def _bar(
    timestamp: datetime,
    strike: float,
    call_put: str,
    bid: float,
    ask: float,
    *,
    underlying_price: float | None = 100.0,
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


def test_diagnose_intraday_selection_reports_missing_underlying_for_delta_mode():
    timestamp = datetime(2026, 5, 22, 9, 45, tzinfo=ZoneInfo("America/New_York"))
    quotes = [
        _bar(timestamp, 93, "Put", 1.0, 1.1, underlying_price=None),
        _bar(timestamp, 107, "Call", 1.0, 1.1, underlying_price=None),
    ]

    diagnostics = diagnose_intraday_selection(
        quotes,
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        entry_time="09:45:00",
        selector=IntradayIronCondorSelectorConfig(selection_mode="delta", target_delta=0.16),
    )

    assert diagnostics.entry_snapshots == 1
    assert diagnostics.reason_counts["missing_underlying_price"] == 1
    assert diagnostics.valid_condors == 0


def test_diagnose_intraday_selection_reports_missing_wing_and_formats_markdown():
    timestamp = datetime(2026, 5, 22, 9, 45, tzinfo=ZoneInfo("America/New_York"))
    quotes = [
        _priced_bar(timestamp, 93, "Put"),
        _priced_bar(timestamp, 107, "Call"),
        _priced_bar(timestamp, 112, "Call"),
    ]

    diagnostics = diagnose_intraday_selection(
        quotes,
        ticker="SPY",
        start=date(2026, 5, 22),
        end=date(2026, 5, 22),
        entry_time="09:45:00",
        selector=IntradayIronCondorSelectorConfig(selection_mode="delta", target_delta=0.16, wing_width=5.0),
    )
    report = format_intraday_selection_report(diagnostics)

    assert diagnostics.entry_snapshots == 1
    assert diagnostics.reason_counts["missing_put_wing"] == 1
    assert diagnostics.valid_condors == 0
    assert "# SPY Intraday Selection Diagnostics" in report
    assert "missing_put_wing" in report
