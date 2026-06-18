"""Iron-condor construction from a point-in-time option chain."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import isclose

from trader.options.models import OptionQuote


@dataclass(frozen=True)
class IronCondorConfig:
    min_dte: int = 30
    max_dte: int = 45
    target_delta: float = 0.16
    wing_width: float = 5.0
    max_wing_width: float = 20.0
    max_delta_deviation: float = 0.08
    min_credit: float = 0.05
    max_bid_ask_spread_pct: float = 1.0


@dataclass(frozen=True)
class IronCondor:
    ticker: str
    trade_date: date
    expiration: date
    short_put: OptionQuote
    long_put: OptionQuote
    short_call: OptionQuote
    long_call: OptionQuote
    entry_credit: float

    @property
    def dte(self) -> int:
        return (self.expiration - self.trade_date).days

    @property
    def put_width(self) -> float:
        return round(self.short_put.strike - self.long_put.strike, 4)

    @property
    def call_width(self) -> float:
        return round(self.long_call.strike - self.short_call.strike, 4)

    @property
    def max_risk(self) -> float:
        return round(max(self.put_width, self.call_width) - self.entry_credit, 4)


def select_iron_condor(chain: list[OptionQuote], config: IronCondorConfig | None = None) -> IronCondor | None:
    """Pick the best 16-delta-ish, fixed-wing iron condor from one chain snapshot."""

    config = config or IronCondorConfig()
    eligible = [
        quote
        for quote in chain
        if quote.has_executable_quote
        and quote.delta is not None
        and config.min_dte <= quote.dte <= config.max_dte
        and _spread_ok(quote, config.max_bid_ask_spread_pct)
    ]
    if not eligible:
        return None

    by_expiration: dict[date, list[OptionQuote]] = defaultdict(list)
    for quote in eligible:
        by_expiration[quote.expiration].append(quote)

    target_dte = (config.min_dte + config.max_dte) / 2.0
    for expiration, quotes in sorted(by_expiration.items(), key=lambda item: abs((item[0] - item[1][0].trade_date).days - target_dte)):
        condor = _select_for_expiration(quotes, config=config, expiration=expiration)
        if condor is not None:
            return condor
    return None


def quote_key(quote: OptionQuote) -> tuple[date, float, str]:
    return (quote.expiration, quote.strike, quote.call_put)


def _select_for_expiration(
    quotes: list[OptionQuote],
    *,
    config: IronCondorConfig,
    expiration: date,
) -> IronCondor | None:
    puts = [quote for quote in quotes if quote.call_put == "Put" and quote.delta is not None and quote.delta < 0]
    calls = [quote for quote in quotes if quote.call_put == "Call" and quote.delta is not None and quote.delta > 0]
    if not puts or not calls:
        return None

    short_puts = sorted(
        [
            quote
            for quote in puts
            if quote.delta is not None and abs(abs(float(quote.delta)) - config.target_delta) <= config.max_delta_deviation
        ],
        key=lambda quote: (abs(abs(float(quote.delta)) - config.target_delta), -quote.strike),
    )
    short_calls = sorted(
        [
            quote
            for quote in calls
            if quote.delta is not None and abs(float(quote.delta) - config.target_delta) <= config.max_delta_deviation
        ],
        key=lambda quote: (abs(float(quote.delta) - config.target_delta), quote.strike),
    )
    if not short_puts or not short_calls:
        return None

    for short_put in short_puts:
        long_put = _find_long_put(puts, short_put, config)
        if long_put is None:
            continue
        for short_call in short_calls:
            long_call = _find_long_call(calls, short_call, config)
            if long_call is None:
                continue
            credit = _entry_credit(short_put, long_put, short_call, long_call)
            if credit < config.min_credit:
                continue
            return IronCondor(
                ticker=short_put.ticker,
                trade_date=short_put.trade_date,
                expiration=expiration,
                short_put=short_put,
                long_put=long_put,
                short_call=short_call,
                long_call=long_call,
                entry_credit=credit,
            )
    return None


def _round_strike(value: float) -> float:
    return round(float(value), 2)


def _find_long_put(puts: list[OptionQuote], short_put: OptionQuote, config: IronCondorConfig) -> OptionQuote | None:
    candidates = [
        quote
        for quote in puts
        if quote.strike < short_put.strike
        and config.wing_width <= short_put.strike - quote.strike <= config.max_wing_width
    ]
    return min(candidates, key=lambda quote: abs((short_put.strike - quote.strike) - config.wing_width), default=None)


def _find_long_call(calls: list[OptionQuote], short_call: OptionQuote, config: IronCondorConfig) -> OptionQuote | None:
    candidates = [
        quote
        for quote in calls
        if quote.strike > short_call.strike
        and config.wing_width <= quote.strike - short_call.strike <= config.max_wing_width
    ]
    return min(candidates, key=lambda quote: abs((quote.strike - short_call.strike) - config.wing_width), default=None)


def _entry_credit(short_put: OptionQuote, long_put: OptionQuote, short_call: OptionQuote, long_call: OptionQuote) -> float:
    if short_put.bid is None or short_call.bid is None or long_put.ask is None or long_call.ask is None:
        return 0.0
    return round(short_put.bid + short_call.bid - long_put.ask - long_call.ask, 4)


def close_debit(short_put: OptionQuote, long_put: OptionQuote, short_call: OptionQuote, long_call: OptionQuote) -> float | None:
    """Conservative close price: buy short legs at ask, sell long legs at bid."""

    if short_put.ask is None or short_call.ask is None or long_put.bid is None or long_call.bid is None:
        return None
    debit = short_put.ask + short_call.ask - long_put.bid - long_call.bid
    return round(max(debit, 0.0), 4)


def condor_intrinsic_debit(condor: IronCondor, underlying_price: float) -> float:
    """Settlement (intrinsic) cost to close the condor at ``underlying_price``.

    Each vertical's value is bounded by ``[0, its width]`` and only one side can be
    in-the-money at a time, so the total is the sum of the two clamped intrinsics.
    This is exactly the cash settlement at expiration and the lower bound on the
    buy-back cost before expiration (a breached spread can never be closed for less
    than it is in-the-money).
    """

    put_value = min(max(condor.short_put.strike - underlying_price, 0.0), condor.put_width)
    call_value = min(max(underlying_price - condor.short_call.strike, 0.0), condor.call_width)
    return round(put_value + call_value, 4)


def bounded_close_debit(
    condor: IronCondor,
    short_put: OptionQuote | None,
    long_put: OptionQuote | None,
    short_call: OptionQuote | None,
    long_call: OptionQuote | None,
    underlying_price: float | None,
    *,
    settle_missing_as_intrinsic: bool = True,
) -> float | None:
    """Close debit constrained by defined-risk reality.

    The raw quote-based debit is unreliable on illiquid/deep-ITM legs: stale or
    missing wing quotes can produce a debit larger than the wing (an impossible
    loss) or hide a breach behind a stale favorable short-leg quote (a fake win).
    We constrain it with the underlying price, which is dense and reliable:

    * **Upper bound** -- the wing width. A defined-risk spread can never cost more
      than its width to close, so the loss can never exceed ``max_risk``.
    * **Lower bound** -- the intrinsic value at the underlying. A breached spread
      can never be bought back for less than it is in-the-money, so this realizes
      breach losses that sparse short-leg quotes would otherwise mask.

    When leg quotes are missing entirely and ``settle_missing_as_intrinsic`` is
    True, we fall back to pure intrinsic settlement from the underlying. That
    fallback is only physically valid **at expiration**: an OTM condor settles to
    zero intrinsic, which mid-life is not a real "closed for ~$0 win" but merely a
    data gap. Callers marking an *open* position (dte > 0) must pass
    ``settle_missing_as_intrinsic=False`` so a missing-quote bar returns ``None``
    (keep the trade open) instead of booking a fabricated max-profit win.
    """

    wing = max(condor.put_width, condor.call_width)
    intrinsic = (
        condor_intrinsic_debit(condor, underlying_price) if underlying_price is not None else None
    )
    quote_debit = None
    if None not in (short_put, long_put, short_call, long_call):
        quote_debit = close_debit(short_put, long_put, short_call, long_call)

    if quote_debit is None:
        if intrinsic is None or not settle_missing_as_intrinsic:
            return None
        return round(min(max(intrinsic, 0.0), wing), 4)

    lower = intrinsic if intrinsic is not None else 0.0
    return round(min(max(quote_debit, lower), wing), 4)


def mark_condor_close_debit(
    condor: IronCondor,
    short_put: OptionQuote | None,
    long_put: OptionQuote | None,
    short_call: OptionQuote | None,
    long_call: OptionQuote | None,
    underlying_price: float | None,
    *,
    dte: int,
    slippage_per_contract: float = 0.0,
) -> float | None:
    """The single marking/settlement core shared by the intraday and EOD engines.

    Both backtest paths MUST price a condor close through this function so they
    cannot diverge (audit 2026-06-06 items A2/B3). Semantics:

    * :func:`bounded_close_debit` -- quote-based debit floored at the intrinsic
      value implied by ``underlying_price`` and capped at the wing width.
    * Intrinsic settlement from the underlying when all leg quotes are missing
      is only permitted **at expiration** (``dte <= 0``); mid-life a missing
      quote returns ``None`` so the caller keeps the position open instead of
      booking a fabricated win on a data gap.
    * ``slippage_per_contract`` is added per leg (4 legs) to the exit debit,
      capped at the wing so the loss still cannot exceed ``max_risk``.
    """

    debit = bounded_close_debit(
        condor,
        short_put,
        long_put,
        short_call,
        long_call,
        underlying_price,
        settle_missing_as_intrinsic=dte <= 0,
    )
    if debit is None:
        return None
    if slippage_per_contract:
        wing = max(condor.put_width, condor.call_width)
        debit = round(min(debit + slippage_per_contract * 4, wing), 4)
    return debit


def same_contract(left: OptionQuote, right: OptionQuote) -> bool:
    return (
        left.ticker == right.ticker
        and left.expiration == right.expiration
        and left.call_put == right.call_put
        and isclose(left.strike, right.strike, abs_tol=0.001)
    )


def _spread_ok(quote: OptionQuote, max_spread_pct: float) -> bool:
    if quote.bid is None or quote.ask is None:
        return False
    mid = quote.mid
    if mid is None or mid <= 0:
        return False
    return ((quote.ask - quote.bid) / mid) <= max_spread_pct
