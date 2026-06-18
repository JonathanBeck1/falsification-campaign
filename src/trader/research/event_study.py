"""Shared market-adjusted event-study primitives.

The campaign's EDGAR / event-driven tests (earnings premium, buyback drift,
spin-off drift, insider clusters, 13F cloning, index reconstitution, IPO lock-up,
CEF cohorts, …) each independently re-implemented the *same* event-study
plumbing: sort a close series, compute beta-1 (market-adjusted) abnormal returns
against a benchmark, and aggregate per-window cumulative abnormal returns into a
``(n, mean, median, pct_positive, t_stat)`` summary. An adversarial code review
flagged this as the second-highest-leverage consolidation after the gate itself:
``_sorted_close`` was byte-identical across at least five modules, and the
abnormal-return and window-aggregation logic was re-derived near-identically in
the rest.

This module is the single home for that plumbing. It is **behaviorally identical**
to the canonical per-module implementations (verified against
``earnings_premium`` / ``insider_clusters``): same dropna→sort→DatetimeIndex,
same ``r_stock - r_bench`` with the benchmark reindexed onto the stock's days and
forward-filled, same NaN-drop + ``ddof=1`` t-stat with the campaign's
0.0-on-degenerate convention (reused from :func:`trader.research.gate.t_stat`).
The per-test ``CAR_WINDOWS`` dicts stay in their modules — those are the genuinely
test-specific *pre-registered design*; only the plumbing underneath is shared.

Everything here is pure (no I/O).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from trader.research.gate import t_stat

__all__ = [
    "WindowStat",
    "abnormal_returns",
    "aggregate_window",
    "cumulative_abnormal_return",
    "sorted_close",
    "t_stat",
]


def sorted_close(series: pd.Series) -> pd.Series:
    """A close series cleaned for event-study use: drop NaN, sort, DatetimeIndex.

    Byte-identical to the ``_sorted_close`` copied across the event-study modules.
    """

    s = series.dropna().sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def abnormal_returns(
    close: pd.Series,
    bench_close: pd.Series,
    *,
    beta: float = 1.0,
) -> pd.Series:
    """Daily market-adjusted abnormal returns ``r_stock - beta*r_bench``.

    ``beta`` defaults to 1.0 (the market-adjusted / beta-one convention every
    campaign event study used). The benchmark is reindexed onto the stock's
    trading days and forward-filled. Pure; the first day is NaN (no prior close).
    """

    stock = sorted_close(close)
    bench = sorted_close(bench_close).reindex(stock.index).ffill()
    return stock.pct_change() - beta * bench.pct_change()


def cumulative_abnormal_return(
    abn: pd.Series,
    t0_pos: int,
    start: int,
    end: int,
) -> float:
    """Cumulative abnormal return over the window ``[t0_pos+start, t0_pos+end]``.

    Positions are integer offsets from the event index ``t0_pos`` into ``abn``
    (already an abnormal-return series). Inclusive of both ends. Returns NaN if
    the window falls outside the available range. Pure.
    """

    lo = t0_pos + start
    hi = t0_pos + end
    if lo < 0 or hi >= len(abn):
        return float("nan")
    window = abn.iloc[lo : hi + 1]
    return float(window.sum())


@dataclass(frozen=True)
class WindowStat:
    """Per-window cohort summary for a set of cumulative abnormal returns."""

    metric: str
    n: int
    mean: float
    median: float
    pct_positive: float
    t_stat: float


def aggregate_window(metric: str, values: Sequence[float]) -> WindowStat:
    """Summarize a list of per-event window values into a :class:`WindowStat`.

    NaNs are dropped. With zero usable values ``mean``/``median``/``pct_positive``
    are NaN and ``t_stat`` is 0.0 (the canonical ``_stat`` convention); otherwise
    the t-stat uses :func:`trader.research.gate.t_stat` (mean / SE, ``ddof=1``,
    0.0 on N<2 or zero variance). Behaviorally identical to the per-module
    ``_stat`` helpers it replaces.
    """

    vals = [float(v) for v in values if v == v]
    n = len(vals)
    if n == 0:
        return WindowStat(metric, 0, float("nan"), float("nan"), float("nan"), 0.0)
    s = pd.Series(vals)
    return WindowStat(
        metric=metric,
        n=n,
        mean=float(s.mean()),
        median=float(s.median()),
        pct_positive=float((s > 0).mean()),
        t_stat=t_stat(vals),
    )
