from __future__ import annotations

from trader.options.greeks import (
    black_scholes_delta,
    black_scholes_price,
    estimate_quote_delta,
    implied_volatility_from_option_price,
)


def test_black_scholes_price_and_delta_are_sane_for_atm_options():
    call_price = black_scholes_price(
        option_type="Call",
        spot=100.0,
        strike=100.0,
        years_to_expiration=30 / 365,
        volatility=0.20,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )
    put_price = black_scholes_price(
        option_type="Put",
        spot=100.0,
        strike=100.0,
        years_to_expiration=30 / 365,
        volatility=0.20,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )
    call_delta = black_scholes_delta(
        option_type="Call",
        spot=100.0,
        strike=100.0,
        years_to_expiration=30 / 365,
        volatility=0.20,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )
    put_delta = black_scholes_delta(
        option_type="Put",
        spot=100.0,
        strike=100.0,
        years_to_expiration=30 / 365,
        volatility=0.20,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )

    assert round(call_price, 2) == 2.49
    assert round(put_price, 2) == 2.08
    assert 0.53 < call_delta < 0.55
    assert -0.47 < put_delta < -0.45


def test_implied_volatility_recovers_input_volatility():
    price = black_scholes_price(
        option_type="Call",
        spot=100.0,
        strike=105.0,
        years_to_expiration=45 / 365,
        volatility=0.28,
        risk_free_rate=0.04,
        dividend_yield=0.0,
    )

    implied_vol = implied_volatility_from_option_price(
        option_type="Call",
        market_price=price,
        spot=100.0,
        strike=105.0,
        years_to_expiration=45 / 365,
        risk_free_rate=0.04,
        dividend_yield=0.0,
    )

    assert implied_vol is not None
    assert abs(implied_vol - 0.28) < 0.001


def test_estimate_quote_delta_returns_none_for_unusable_inputs():
    assert (
        estimate_quote_delta(
            option_type="Call",
            option_mid=None,
            spot=100.0,
            strike=100.0,
            years_to_expiration=30 / 365,
            risk_free_rate=0.04,
            dividend_yield=0.0,
        )
        is None
    )
    assert (
        estimate_quote_delta(
            option_type="Put",
            option_mid=1.0,
            spot=None,
            strike=100.0,
            years_to_expiration=30 / 365,
            risk_free_rate=0.04,
            dividend_yield=0.0,
        )
        is None
    )
