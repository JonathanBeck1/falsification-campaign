"""Small Black-Scholes helpers for research-only option delta estimation."""

from __future__ import annotations

from math import erf, exp, isfinite, log, sqrt
from typing import Literal

OptionType = Literal["Call", "Put"]


def black_scholes_price(
    *,
    option_type: OptionType,
    spot: float,
    strike: float,
    years_to_expiration: float,
    volatility: float,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
) -> float:
    """Return European Black-Scholes theoretical option price."""

    if not _inputs_ok(spot=spot, strike=strike, years=years_to_expiration, volatility=volatility):
        return 0.0
    d1, d2 = _d1_d2(
        spot=spot,
        strike=strike,
        years_to_expiration=years_to_expiration,
        volatility=volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    discounted_spot = spot * exp(-dividend_yield * years_to_expiration)
    discounted_strike = strike * exp(-risk_free_rate * years_to_expiration)
    if option_type == "Call":
        return max(discounted_spot * _norm_cdf(d1) - discounted_strike * _norm_cdf(d2), 0.0)
    return max(discounted_strike * _norm_cdf(-d2) - discounted_spot * _norm_cdf(-d1), 0.0)


def black_scholes_delta(
    *,
    option_type: OptionType,
    spot: float,
    strike: float,
    years_to_expiration: float,
    volatility: float,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
) -> float:
    """Return European Black-Scholes delta."""

    if not _inputs_ok(spot=spot, strike=strike, years=years_to_expiration, volatility=volatility):
        return 0.0
    d1, _ = _d1_d2(
        spot=spot,
        strike=strike,
        years_to_expiration=years_to_expiration,
        volatility=volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    discount = exp(-dividend_yield * years_to_expiration)
    if option_type == "Call":
        return discount * _norm_cdf(d1)
    return discount * (_norm_cdf(d1) - 1.0)


def implied_volatility_from_option_price(
    *,
    option_type: OptionType,
    market_price: float | None,
    spot: float,
    strike: float,
    years_to_expiration: float,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
    min_volatility: float = 0.01,
    max_volatility: float = 5.0,
    tolerance: float = 0.0001,
    max_iterations: int = 80,
) -> float | None:
    """Infer IV with bisection. Returns None when the quote is unusable."""

    if market_price is None or market_price <= 0:
        return None
    if not _inputs_ok(spot=spot, strike=strike, years=years_to_expiration, volatility=min_volatility):
        return None
    low = min_volatility
    high = max_volatility
    low_price = black_scholes_price(
        option_type=option_type,
        spot=spot,
        strike=strike,
        years_to_expiration=years_to_expiration,
        volatility=low,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    high_price = black_scholes_price(
        option_type=option_type,
        spot=spot,
        strike=strike,
        years_to_expiration=years_to_expiration,
        volatility=high,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    if market_price < low_price - tolerance or market_price > high_price + tolerance:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        model_price = black_scholes_price(
            option_type=option_type,
            spot=spot,
            strike=strike,
            years_to_expiration=years_to_expiration,
            volatility=mid,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
        )
        if abs(model_price - market_price) <= tolerance:
            return mid
        if model_price < market_price:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def estimate_quote_delta(
    *,
    option_type: OptionType,
    option_mid: float | None,
    spot: float | None,
    strike: float,
    years_to_expiration: float,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
) -> float | None:
    """Estimate delta from one option mid quote and underlying spot."""

    if option_mid is None or spot is None:
        return None
    implied_volatility = implied_volatility_from_option_price(
        option_type=option_type,
        market_price=option_mid,
        spot=spot,
        strike=strike,
        years_to_expiration=years_to_expiration,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    if implied_volatility is None:
        return None
    return black_scholes_delta(
        option_type=option_type,
        spot=spot,
        strike=strike,
        years_to_expiration=years_to_expiration,
        volatility=implied_volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )


def _d1_d2(
    *,
    spot: float,
    strike: float,
    years_to_expiration: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> tuple[float, float]:
    denominator = volatility * sqrt(years_to_expiration)
    d1 = (
        log(spot / strike)
        + (risk_free_rate - dividend_yield + (volatility * volatility) / 2.0) * years_to_expiration
    ) / denominator
    return d1, d1 - denominator


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _inputs_ok(*, spot: float, strike: float, years: float, volatility: float) -> bool:
    return all(isfinite(value) and value > 0 for value in (spot, strike, years, volatility))
