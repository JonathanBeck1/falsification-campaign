"""Buy-and-hold benchmark comparison (alpha) for options backtests.

Pure and I/O-free: callers pass an ordered underlying close-price series (from
``historical_bars`` or the underlying quotes) and a strategy return. We compute
the underlying buy-and-hold return over the same window and the excess return
(alpha = strategy - benchmark) so the standardized report can show strategy vs
benchmark vs alpha side by side.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from trader.backtesting.baselines.buy_and_hold import buy_and_hold_return


@dataclass(frozen=True)
class BenchmarkComparison:
    strategy_return: float
    benchmark_return: float | None
    alpha: float | None


def closes_from_historical_bars(
    bars: Sequence[Mapping[str, object]],
    *,
    since: date | str | None = None,
    until: date | str | None = None,
    price_key: str = "close",
) -> list[float]:
    """Extract an ordered close-price series from ``historical_bars`` rows.

    Rows are expected to carry ``trade_date`` and ``close`` (the schema of
    ``Store.get_historical_bars``). Filters to ``[since, until]`` inclusive and
    sorts ascending by trade_date so the first/last prices bound the window.
    """
    lo = _as_iso(since)
    hi = _as_iso(until)
    rows: list[tuple[str, float]] = []
    for bar in bars:
        trade_date = str(bar["trade_date"])
        if lo is not None and trade_date < lo:
            continue
        if hi is not None and trade_date > hi:
            continue
        price = bar.get(price_key)
        if price is None:
            continue
        rows.append((trade_date, float(price)))
    rows.sort(key=lambda item: item[0])
    return [price for _trade_date, price in rows]


def buy_and_hold_benchmark(
    prices: Sequence[float],
    *,
    strategy_return: float,
) -> dict[str, float | None]:
    """Return ``{benchmark_return, alpha}`` for merging into a metrics dict.

    ``alpha`` is ``strategy_return - benchmark_return`` (None when the price
    series is too short to form a benchmark).
    """
    benchmark = buy_and_hold_return(prices)
    alpha = None if benchmark is None else round(strategy_return - benchmark, 6)
    return {"benchmark_return": benchmark, "alpha": alpha}


def compare(
    prices: Sequence[float],
    *,
    strategy_return: float,
) -> BenchmarkComparison:
    result = buy_and_hold_benchmark(prices, strategy_return=strategy_return)
    return BenchmarkComparison(
        strategy_return=strategy_return,
        benchmark_return=result["benchmark_return"],
        alpha=result["alpha"],
    )


def _as_iso(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
