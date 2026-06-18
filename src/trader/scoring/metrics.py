"""Pure-function performance metrics for the horse-race leaderboard.

Every function here takes a sorted-ascending `equity_curve: list[tuple[date, float]]`
or a precomputed `daily_returns: list[float]`. No I/O, no SQLite. Easy to unit
test with hand-built series.
"""

from __future__ import annotations

import math
from datetime import date
from statistics import mean, stdev


def daily_returns(equity_curve: list[tuple[date, float]]) -> list[float]:
    """Day-over-day percent returns. Length is len(curve) - 1.

    Returns [] for empty or single-point curves. Skips pairs where the prior
    equity is non-positive (avoids divide-by-zero on seeded zero-cash brains).
    """
    if len(equity_curve) < 2:
        return []
    out: list[float] = []
    prev = equity_curve[0][1]
    for _trade_date, eq in equity_curve[1:]:
        if prev > 0:
            out.append((eq - prev) / prev)
        prev = eq
    return out


def total_return(equity_curve: list[tuple[date, float]]) -> float:
    """(final / first) - 1. Returns 0.0 if len(curve) < 2 or first <= 0."""
    if len(equity_curve) < 2:
        return 0.0
    first = equity_curve[0][1]
    last = equity_curve[-1][1]
    if first <= 0:
        return 0.0
    return (last / first) - 1.0


def annualized_return(
    equity_curve: list[tuple[date, float]],
    *,
    trading_days_per_year: int = 252,
) -> float:
    """Geometric annualization from total return + observed day span.

    Returns 0.0 if fewer than 2 points or non-positive first equity.
    Uses `(1 + r) ^ (trading_days_per_year / n_days) - 1` where n_days is
    the number of observed daily intervals (len(curve) - 1).
    """
    if len(equity_curve) < 2:
        return 0.0
    first = equity_curve[0][1]
    last = equity_curve[-1][1]
    if first <= 0 or last <= 0:
        return 0.0
    n_intervals = len(equity_curve) - 1
    if n_intervals <= 0:
        return 0.0
    growth = last / first
    return growth ** (trading_days_per_year / n_intervals) - 1.0


def sharpe_ratio(
    daily_rets: list[float], *, trading_days_per_year: int = 252
) -> float:
    """Annualized Sharpe at zero risk-free rate.

    Returns 0.0 if fewer than 2 returns or if the std of returns is zero.
    """
    if len(daily_rets) < 2:
        return 0.0
    sigma = stdev(daily_rets)
    if sigma == 0:
        return 0.0
    return mean(daily_rets) / sigma * math.sqrt(trading_days_per_year)


def max_drawdown(equity_curve: list[tuple[date, float]]) -> float:
    """Peak-to-trough max decline. Returns 0.0 (no drawdown) for monotone
    or single-point curves. Negative-or-zero result (e.g. -0.20 means 20%
    drawdown)."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0][1]
    worst = 0.0
    for _trade_date, eq in equity_curve[1:]:
        if eq > peak:
            peak = eq
            continue
        if peak <= 0:
            continue
        dd = (eq - peak) / peak
        if dd < worst:
            worst = dd
    return worst


def hit_rate(daily_rets: list[float]) -> float:
    """Fraction of positive daily returns. 0.5 if fewer than 1 return."""
    if not daily_rets:
        return 0.5
    wins = sum(1 for r in daily_rets if r > 0)
    return wins / len(daily_rets)
