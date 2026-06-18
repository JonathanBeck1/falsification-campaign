"""Phase 2: pattern analysis + falsifiable drift tests on the news catalog.

The catalog tells us WHAT category each large-move event was. Phase 2 asks: do
any categories produce post-move *drift* that beats noise after the appropriate
multiple-testing correction?

Window discipline (lesson from the PEAD look-ahead kill):
  - t0 = the move date itself (already realized at end of day t0)
  - CAR window starts at t0+1 (do NOT include t0 in the measurement window)
  - Market-adjusted vs SPY (beta=1, conservative)

Gate per (category, direction) cohort:
  - N >= 30
  - Mean CAR[+1,+21] significantly different from 0 (|t| >= 2)
  - Same sign in early (2020-2022) vs late (2023-2026) OOS halves

Honest prior: deflated Sharpe correction across ~14 categories x 2 directions
= ~28 trials means we'd expect ~1.4 "p<0.05 winners" from pure noise. Apply the
deflation accordingly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class DriftMetrics:
    category: str
    direction: str
    n: int
    mean_car_p1_p5: float
    mean_car_p1_p21: float
    mean_car_p1_p63: float
    median_car_p1_p21: float
    t_p1_p21: float
    pct_positive_p21: float
    n_early: int
    n_late: int
    mean_early: float
    mean_late: float


def _ar_series(close: pd.Series, spy: pd.Series) -> pd.Series:
    """Market-adjusted daily abnormal return = stock return - SPY return."""
    r = close.pct_change()
    s = spy.reindex(close.index).ffill().pct_change()
    return (r - s).dropna()


def compute_drift_for_event(
    close: pd.Series, spy_close: pd.Series, event_date: date,
    *, windows: tuple[tuple[int, int], ...] = ((1, 5), (1, 21), (1, 63)),
) -> dict[str, float] | None:
    """For one event, compute market-adjusted CAR over each window starting at t0+1.

    Returns None if event date is missing from price series or window incomplete.
    """
    close = close.dropna().sort_index()
    spy_close = spy_close.dropna().sort_index()
    if len(close) < 100:
        return None
    dates = close.index
    pos = dates.searchsorted(pd.Timestamp(event_date), side="left")
    if pos >= len(dates) or dates[pos].date() != event_date:
        return None
    t0 = int(pos)
    ar = _ar_series(close, spy_close)
    if t0 + 1 not in range(len(ar)):
        return None
    out = {}
    for a, b in windows:
        if t0 + b >= len(ar):
            out[f"car_p{a}_p{b}"] = float("nan")
        else:
            out[f"car_p{a}_p{b}"] = float(ar.iloc[t0 + a : t0 + b + 1].sum())
    return out


def _t_stat(values: list[float]) -> float:
    vals = [v for v in values if v == v]
    n = len(vals)
    if n < 2:
        return 0.0
    s = pd.Series(vals)
    sd = float(s.std(ddof=1))
    if sd == 0:
        return 0.0
    return float(s.mean() / (sd / math.sqrt(n)))


def aggregate_cohort(events_with_drift: pd.DataFrame, category: str, direction: str) -> DriftMetrics | None:
    """events_with_drift: must have columns category, direction, date, car_p1_p5/21/63."""
    sub = events_with_drift[
        (events_with_drift["category"] == category)
        & (events_with_drift["direction"] == direction)
    ].copy()
    sub = sub.dropna(subset=["car_p1_p21"])
    n = len(sub)
    if n == 0:
        return None
    sub["year"] = pd.to_datetime(sub["date"]).dt.year
    early = sub[sub.year <= 2022]
    late = sub[sub.year > 2022]
    return DriftMetrics(
        category=category,
        direction=direction,
        n=n,
        mean_car_p1_p5=float(sub["car_p1_p5"].mean()),
        mean_car_p1_p21=float(sub["car_p1_p21"].mean()),
        mean_car_p1_p63=float(sub["car_p1_p63"].mean()) if "car_p1_p63" in sub else float("nan"),
        median_car_p1_p21=float(sub["car_p1_p21"].median()),
        t_p1_p21=_t_stat(sub["car_p1_p21"].tolist()),
        pct_positive_p21=float((sub["car_p1_p21"] > 0).mean()),
        n_early=len(early),
        n_late=len(late),
        mean_early=float(early["car_p1_p21"].mean()) if len(early) else float("nan"),
        mean_late=float(late["car_p1_p21"].mean()) if len(late) else float("nan"),
    )


@dataclass(frozen=True)
class GateVerdict:
    cohort: str
    passed: bool
    reasons: list[str]


def evaluate_drift_gate(
    m: DriftMetrics, *, min_n: int = 30, t_threshold: float = 2.0,
) -> GateVerdict:
    reasons: list[str] = []
    enough_n = m.n >= min_n
    reasons.append(
        f"{'PASS' if enough_n else 'FAIL'}: N={m.n} (need >= {min_n})"
    )
    sig = abs(m.t_p1_p21) >= t_threshold
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: CAR[+1,+21] mean={m.mean_car_p1_p21*100:+.2f}% "
        f"t={m.t_p1_p21:+.2f} (need |t|>={t_threshold})"
    )
    same_sign = False
    if m.n_early >= 10 and m.n_late >= 10 and not (m.mean_early != m.mean_early or m.mean_late != m.mean_late):
        same_sign = (m.mean_early > 0 and m.mean_late > 0) or (m.mean_early < 0 and m.mean_late < 0)
    reasons.append(
        f"{'PASS' if same_sign else 'FAIL'}: OOS sign stable — early={m.mean_early*100:+.2f}% "
        f"(N={m.n_early}) late={m.mean_late*100:+.2f}% (N={m.n_late})"
    )
    return GateVerdict(
        cohort=f"{m.category}__{m.direction}",
        passed=enough_n and sig and same_sign,
        reasons=reasons,
    )
