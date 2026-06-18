"""Event studies for post-earnings drift and SEC 8-K item disclosures.

The PEAD study splits earnings events into positive and negative cohorts using
the announcement-day close-to-close return as a proxy for surprise sign, then
measures whether market-adjusted returns continue in that direction. The 8-K
study classifies filing text by disclosed item number and uses the same generic
CAR machinery to compare forced-disclosure categories.

Everything here is pure and unit-tested on synthetic series; no I/O.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from trader.research.event_study import sorted_close

log = structlog.get_logger()

# Event-time windows, in trading days relative to t0 (inclusive ranges).
CAR_WINDOWS: dict[str, tuple[int, int]] = {
    "car_m1_p1": (-1, 1),
    "car_0_p5": (0, 5),
    "car_0_p21": (0, 21),
    "car_0_p63": (0, 63),
}
NEED_LO = min(window[0] for window in CAR_WINDOWS.values())
NEED_HI = max(window[1] for window in CAR_WINDOWS.values())

_ITEM_RE = re.compile(r"Item\s+(\d\.\d{2})", re.IGNORECASE)


@dataclass(frozen=True)
class PeadEvent:
    """Per-earnings-event reaction and market-adjusted returns."""

    ticker: str
    event_date: date
    t0_date: date
    prev_day_reaction: float
    car_m1_p1: float
    car_0_p5: float
    car_0_p21: float
    car_0_p63: float


@dataclass(frozen=True)
class CohortStats:
    """Mean, median, and t-statistics for one PEAD cohort."""

    label: str
    n: int
    means: dict[str, float]
    medians: dict[str, float]
    t_stats: dict[str, float]


def _event_position(index: pd.DatetimeIndex, event_date: date, offset: int = 0) -> int:
    return int(index.searchsorted(pd.Timestamp(event_date), side="left")) + offset


def _abnormal_returns(close: pd.Series, bench_close: pd.Series) -> pd.Series:
    bench = sorted_close(bench_close).reindex(close.index).ffill()
    return close.pct_change() - bench.pct_change()


def compute_pead_event(
    close: pd.Series,
    bench_close: pd.Series,
    earnings_date: date,
    *,
    offset: int = 0,
) -> PeadEvent | None:
    """Compute one earnings event's reaction and CARs, or ``None`` if incomplete.

    t0 is the first stock trading day on or after ``earnings_date``, shifted by
    ``offset`` trading days. Abnormal return is the stock return minus the
    benchmark return (beta=1).
    """

    close = sorted_close(close)
    bench_close = sorted_close(bench_close)
    if len(close) < (NEED_HI - NEED_LO + 1):
        return None

    dates = close.index
    t0 = _event_position(dates, earnings_date, offset)
    if t0 < 0 or t0 >= len(dates):
        return None
    if t0 + NEED_LO < 0 or t0 + NEED_HI >= len(dates):
        return None

    ar = _abnormal_returns(close, bench_close)

    def _car(a: int, b: int) -> float:
        return float(ar.iloc[t0 + a : t0 + b + 1].sum())

    return PeadEvent(
        ticker=str(close.name) if close.name else "",
        event_date=earnings_date,
        t0_date=dates[t0].date(),
        prev_day_reaction=float(close.iloc[t0] / close.iloc[t0 - 1] - 1),
        car_m1_p1=_car(*CAR_WINDOWS["car_m1_p1"]),
        car_0_p5=_car(*CAR_WINDOWS["car_0_p5"]),
        car_0_p21=_car(*CAR_WINDOWS["car_0_p21"]),
        car_0_p63=_car(*CAR_WINDOWS["car_0_p63"]),
    )


def compute_event_cars(
    close: pd.Series,
    bench: pd.Series,
    event_date: date,
    windows: dict[str, tuple[int, int]],
) -> dict[str, float]:
    """Return market-adjusted CARs for arbitrary inclusive event windows."""

    if not windows:
        return {}

    close = sorted_close(close)
    bench = sorted_close(bench)
    if close.empty:
        return {}

    lo = min(window[0] for window in windows.values())
    hi = max(window[1] for window in windows.values())
    if any(start > end for start, end in windows.values()):
        return {}

    dates = close.index
    t0 = _event_position(dates, event_date)
    if t0 < 0 or t0 >= len(dates):
        return {}
    if t0 + lo < 0 or t0 + hi >= len(dates):
        return {}

    ar = _abnormal_returns(close, bench)
    return {
        name: float(ar.iloc[t0 + start : t0 + end + 1].sum())
        for name, (start, end) in windows.items()
    }


def classify_8k_items(text: str) -> set[str]:
    """Return the distinct SEC 8-K item numbers found in filing text."""

    return set(_ITEM_RE.findall(text))


def _t_stat(values: list[float]) -> float:
    vals = [value for value in values if value == value]
    n = len(vals)
    if n < 2:
        return 0.0
    series = pd.Series(vals)
    std = float(series.std(ddof=1))
    if std == 0:
        return 0.0
    return float(series.mean() / (std / math.sqrt(n)))


def aggregate_cohort(events: list[PeadEvent], label: str) -> CohortStats:
    """Aggregate PEAD CAR fields into mean, median, and t-stat per window."""

    values = {
        name: [float(getattr(event, name)) for event in events] for name in CAR_WINDOWS
    }
    means = {
        name: float(pd.Series(metric_values).mean()) if metric_values else float("nan")
        for name, metric_values in values.items()
    }
    medians = {
        name: float(pd.Series(metric_values).median()) if metric_values else float("nan")
        for name, metric_values in values.items()
    }
    t_stats = {
        name: _t_stat(metric_values) for name, metric_values in values.items()
    }
    return CohortStats(
        label=label,
        n=len(events),
        means=means,
        medians=medians,
        t_stats=t_stats,
    )
