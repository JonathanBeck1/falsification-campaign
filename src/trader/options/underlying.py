"""Underlying spot enrichment for option quote bars."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime
from math import exp
from statistics import median

from trader.options.models import OptionQuoteBar, UnderlyingQuoteBar


def attach_underlying_quote_prices(
    quote_bars: list[OptionQuoteBar],
    underlying_bars: list[UnderlyingQuoteBar],
) -> list[OptionQuoteBar]:
    """Attach exact-timestamp underlying mids from a stock quote stream."""

    prices_by_timestamp = {bar.timestamp: bar.mid for bar in underlying_bars if bar.mid is not None}
    if not prices_by_timestamp:
        return quote_bars
    return [
        replace(quote, underlying_price=prices_by_timestamp[quote.timestamp])
        if quote.underlying_price is None and quote.timestamp in prices_by_timestamp
        else quote
        for quote in quote_bars
    ]


def attach_put_call_parity_underlying_prices(
    quote_bars: list[OptionQuoteBar],
    *,
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> list[OptionQuoteBar]:
    """Derive underlying spot from paired call/put mids using put-call parity.

    For each timestamp/expiration, paired call and put quotes at the same strike
    imply:

        S = (C - P + K * exp(-rT)) / exp(-qT)

    The median implied spot across available pairs is attached to every option
    quote in that timestamp/expiration group.
    """

    by_group: dict[tuple[datetime, date], list[OptionQuoteBar]] = defaultdict(list)
    for quote in quote_bars:
        by_group[(quote.timestamp, quote.expiration)].append(quote)

    prices_by_group: dict[tuple[datetime, date], float] = {}
    for key, group in by_group.items():
        timestamp, expiration = key
        years_to_expiration = (expiration - timestamp.date()).days / 365
        if years_to_expiration <= 0:
            continue
        by_strike: dict[float, dict[str, OptionQuoteBar]] = defaultdict(dict)
        for quote in group:
            if quote.mid is None:
                continue
            by_strike[quote.strike][quote.call_put] = quote
        implied_spots = [
            _put_call_parity_spot(
                call_mid=pair["Call"].mid,
                put_mid=pair["Put"].mid,
                strike=strike,
                years_to_expiration=years_to_expiration,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
            )
            for strike, pair in by_strike.items()
            if "Call" in pair and "Put" in pair and pair["Call"].mid is not None and pair["Put"].mid is not None
        ]
        clean = [spot for spot in implied_spots if spot is not None and spot > 0]
        if clean:
            prices_by_group[key] = round(median(clean), 4)

    if not prices_by_group:
        return quote_bars
    return [
        replace(quote, underlying_price=prices_by_group[(quote.timestamp, quote.expiration)])
        if quote.underlying_price is None and (quote.timestamp, quote.expiration) in prices_by_group
        else quote
        for quote in quote_bars
    ]


def _put_call_parity_spot(
    *,
    call_mid: float | None,
    put_mid: float | None,
    strike: float,
    years_to_expiration: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float | None:
    if call_mid is None or put_mid is None:
        return None
    return (call_mid - put_mid + strike * exp(-risk_free_rate * years_to_expiration)) / exp(
        -dividend_yield * years_to_expiration
    )
