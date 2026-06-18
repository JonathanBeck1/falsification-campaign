from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from trader.options.greeks import black_scholes_price
from trader.options.models import OptionQuoteBar
from trader.options.underlying import attach_put_call_parity_underlying_prices


def _bar(timestamp: datetime, strike: float, call_put: str, mid: float) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker="SPY",
        expiration=date(2026, 6, 26),
        strike=strike,
        call_put=call_put,
        bid=mid - 0.01,
        ask=mid + 0.01,
        source="unit-test",
    )


def test_attach_put_call_parity_underlying_prices_fills_option_bars_without_stock_endpoint():
    timestamp = datetime(2026, 5, 22, 9, 45, tzinfo=ZoneInfo("America/New_York"))
    spot = 586.12
    expiration = date(2026, 6, 26)
    years = (expiration - timestamp.date()).days / 365
    call_mid = black_scholes_price(
        option_type="Call",
        spot=spot,
        strike=586.0,
        years_to_expiration=years,
        volatility=0.22,
        risk_free_rate=0.04,
        dividend_yield=0.0,
    )
    put_mid = black_scholes_price(
        option_type="Put",
        spot=spot,
        strike=586.0,
        years_to_expiration=years,
        volatility=0.22,
        risk_free_rate=0.04,
        dividend_yield=0.0,
    )
    bars = [
        _bar(timestamp, 586.0, "Call", call_mid),
        _bar(timestamp, 586.0, "Put", put_mid),
        _bar(timestamp, 600.0, "Call", 3.0),
    ]

    enriched = attach_put_call_parity_underlying_prices(
        bars,
        risk_free_rate=0.04,
        dividend_yield=0.0,
    )

    assert all(bar.underlying_price is not None for bar in enriched)
    assert abs(enriched[0].underlying_price - spot) < 0.05
    assert enriched[2].underlying_price == enriched[0].underlying_price
