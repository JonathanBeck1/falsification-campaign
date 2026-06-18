"""Campaign test T39 — S&P 500 index reconstitution / the "index effect".

Pre-registered in ``research/index_reconstitution_preregistration.md``.
Falsify-first. The PREDICTED outcome is a decayed null.

Hypothesis: stocks ADDED to the S&P 500 earn a positive market-adjusted CAR over
the **announcement -> effective** window (forced index-fund buying on pre-known
dates); deletions earn a negative one. Mechanism: forced, price-insensitive
index-fund flow. Honest prior: the effect has decayed to ~0 since the 2000s
(Greenwood & Sammon 2023) -- we expect a KILL.

This module is the part the prior effective-date T-study explicitly left
UNTESTED: the announce->effective forced-flow window. A clean, free, complete
announcement-date series does not exist (see pre-reg §3 for the verified data
wall), so the announcement date is a **pre-registered ex-ante proxy**:
``t_announce = t_effective - ANNOUNCE_LEAD_TD`` trading days, with the lead
calibrated (median 6 calendar / ~5 trading days) on the independent subset of
Wikipedia rows that carry both dates.

Everything here is **pure**: it operates on in-memory price series and an event
list and does no I/O. The event list is produced by the snapshot-diff parser
reused from ``index_rebalance`` (also pure); only the runner touches the network.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

import pandas as pd

# Re-use the proven, unit-tested snapshot-diff event machinery. These are pure.
from trader.catalysts.index_rebalance import (  # noqa: F401  (re-exported for runner/tests)
    DefaultIndexChangeProvider,
    IndexChange,
    IndexChangeProvider,
    changes_from_snapshots,
    load_changes,
    parse_snapshot_csv,
)

# Shared event-study / gate plumbing. ``sorted_close`` is byte-identical to the
# former local ``_sorted_close``; ``t_stat`` is behaviorally identical to the
# former local ``_t_stat`` (same NaN-drop, ddof=1, 0.0-on-degenerate, ``null=``).
from trader.research.event_study import sorted_close
from trader.research.gate import t_stat

# Pre-registered announcement-date proxy: S&P announces ~1 week (median 6 calendar
# / ~5 trading days) before the change is effective. FIXED constant (not fit to
# the measured prices). The primary uses 5; the runner reports a {3,7} band.
ANNOUNCE_LEAD_TD = 5

# Event-time CAR windows, trading days relative to the EFFECTIVE day (t=0).
# The PRIMARY is the announce->effective forced-flow window [-lead, 0].
CAR_WINDOWS: dict[str, tuple[int, int]] = {
    "car_announce_eff": (-ANNOUNCE_LEAD_TD, 0),   # PRIMARY: forced-flow window
    "car_announce_m1": (-ANNOUNCE_LEAD_TD, -1),   # pure announcement run-up
    "car_eff_p5": (0, 5),                         # post-effective reversal check
}
PRIMARY_WINDOW = "car_announce_eff"
NEED_LO = min(w[0] for w in CAR_WINDOWS.values())
NEED_HI = max(w[1] for w in CAR_WINDOWS.values())

# A single-day market-adjusted return beyond this magnitude is, for an S&P 500
# constituent, almost certainly a yfinance data glitch (unadjusted split / bad
# near-zero print), not a real flow move. The event is dropped (counted, hidden
# from nothing). Matches the prior T-study's calibrated 75% guard.
MAX_ABS_DAILY_AR = 0.75

# Round-trip friction for a liquid large-cap single name (pre-reg §6): 10 bps.
ROUND_TRIP_COST = 0.0010

# IS / OOS split boundary (pre-registered): IS = effective year <= 2017.
OOS_SPLIT_YEAR = 2018


# --------------------------------------------------------------------------- #
# CAR math (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EventMetrics:
    """Per-event market-adjusted CARs in event time (anchored on effective day)."""

    ticker: str
    effective_date: date
    t0_date: date  # resolved effective trading day
    kind: str  # "add" or "delete"
    car_announce_eff: float
    car_announce_m1: float
    car_eff_p5: float


@dataclass(frozen=True)
class WindowAgg:
    metric: str
    n: int
    mean: float
    median: float
    pct_positive: float
    t_stat: float


@dataclass(frozen=True)
class StudyResult:
    label: str
    n_events: int
    windows: dict[str, WindowAgg]


def _abnormal_return(close: pd.Series, spy_close: pd.Series) -> pd.Series:
    """Market-adjusted (beta=1) abnormal-return series aligned to ``close``'s dates."""

    close = sorted_close(close)
    ret = close.pct_change()
    spy = sorted_close(spy_close).reindex(close.index).ffill()
    return ret - spy.pct_change()


def compute_event_metrics(
    close: pd.Series,
    spy_close: pd.Series,
    effective_date: date,
    *,
    kind: str,
    announce_lead_td: int = ANNOUNCE_LEAD_TD,
) -> EventMetrics | None:
    """Compute one event's announce->effective market-adjusted CARs.

    t0 = first trading day on/after ``effective_date``; the announcement is
    proxied at ``t0 - announce_lead_td``. Returns ``None`` if the full
    ``[lo, hi]`` window around t0 is not present (thin data / purged deletion) or
    if any single-day AR inside the window is an absurd glitch.
    """

    close = sorted_close(close)
    lo = -announce_lead_td
    hi = NEED_HI
    if len(close) < (hi - lo + 2):
        return None

    dates = close.index
    t0 = int(dates.searchsorted(pd.Timestamp(effective_date), side="left"))
    if t0 < 0 or t0 >= len(dates):
        return None
    if t0 + lo < 0 or t0 + hi >= len(dates):
        return None

    ar = _abnormal_return(close, spy_close)

    win = ar.iloc[t0 + lo : t0 + hi + 1]
    if (win.abs() > MAX_ABS_DAILY_AR).any():
        return None

    def _car(a: int, b: int) -> float:
        return float(ar.iloc[t0 + a : t0 + b + 1].sum())

    return EventMetrics(
        ticker=str(close.name) if close.name else "",
        effective_date=effective_date,
        t0_date=dates[t0].date(),
        kind=kind,
        car_announce_eff=_car(-announce_lead_td, 0),
        car_announce_m1=_car(-announce_lead_td, -1),
        car_eff_p5=_car(*CAR_WINDOWS["car_eff_p5"]),
    )


def placebo_cars(
    close: pd.Series,
    spy_close: pd.Series,
    *,
    window_len: int = ANNOUNCE_LEAD_TD + 1,
    n_draws: int,
    rng: random.Random,
) -> list[float]:
    """Random non-event CARs of the same width on the SAME name (placebo control).

    Draws ``n_draws`` random ``window_len``-day windows from the name's own
    abnormal-return series and returns each window's CAR. A real forced-flow edge
    must NOT appear in these random windows. Pure (rng injected). Glitch windows
    are skipped (counted as fewer draws), never hidden.
    """

    ar = _abnormal_return(close, spy_close).dropna()
    n = len(ar)
    if n < window_len + 1:
        return []
    out: list[float] = []
    hi = n - window_len
    for _ in range(n_draws):
        start = rng.randint(1, hi)  # skip index 0 (NaN pct_change)
        seg = ar.iloc[start : start + window_len]
        if (seg.abs() > MAX_ABS_DAILY_AR).any():
            continue
        out.append(float(seg.sum()))
    return out


def _agg(metric: str, values: list[float]) -> WindowAgg:
    vals = [v for v in values if v == v]
    n = len(vals)
    if n == 0:
        return WindowAgg(metric, 0, float("nan"), float("nan"), float("nan"), 0.0)
    s = pd.Series(vals)
    return WindowAgg(
        metric=metric,
        n=n,
        mean=float(s.mean()),
        median=float(s.median()),
        pct_positive=float((s > 0).mean()),
        t_stat=t_stat(vals),
    )


def aggregate(metrics: list[EventMetrics], *, label: str) -> StudyResult:
    """Aggregate per-event CARs into mean/median/%pos/t-stat per window. Pure."""

    windows = {
        name: _agg(name, [getattr(m, name) for m in metrics]) for name in CAR_WINDOWS
    }
    return StudyResult(label=label, n_events=len(metrics), windows=windows)


def after_cost_mean(window: WindowAgg, *, round_trip: float = ROUND_TRIP_COST) -> float:
    """Subtract one round-trip cost from a window's gross mean CAR."""

    return window.mean - round_trip


def split_is_oos(
    metrics: list[EventMetrics], *, split_year: int = OOS_SPLIT_YEAR
) -> tuple[list[EventMetrics], list[EventMetrics]]:
    """Partition events into IS (effective year < split_year) and OOS halves."""

    is_ = [m for m in metrics if m.effective_date.year < split_year]
    oos = [m for m in metrics if m.effective_date.year >= split_year]
    return is_, oos


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    adds: StudyResult,
    is_adds: StudyResult,
    oos_adds: StudyResult,
    placebo: WindowAgg,
    *,
    min_events: int = 30,
    t_threshold: float = 2.0,
    round_trip: float = ROUND_TRIP_COST,
) -> GateVerdict:
    """Pre-registered ADDITIONS gate (ALL must hold), PRIMARY = announce->effective.

    N>=min_events; AFTER-COST primary CAR positive with |t|>=t_threshold; IS/OOS
    same sign; placebo null AND cohort survives placebo. The decay comparison is
    reported by the runner regardless of pass/fail.
    """

    reasons: list[str] = []
    car = adds.windows[PRIMARY_WINDOW]
    net = after_cost_mean(car, round_trip=round_trip)

    enough = adds.n_events >= min_events
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: N={adds.n_events} (need >= {min_events})"
    )

    sig = (net > 0) and (abs(car.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: after-cost signal — {PRIMARY_WINDOW} "
        f"net={net:+.4f} (gross={car.mean:+.4f}) t={car.t_stat:+.2f} "
        f"(need net>0 & |t|>={t_threshold})"
    )

    early = is_adds.windows[PRIMARY_WINDOW].mean
    late = oos_adds.windows[PRIMARY_WINDOW].mean
    same_sign = (early > 0 and late > 0) or (early < 0 and late < 0)
    reasons.append(
        f"{'PASS' if same_sign else 'FAIL'}: OOS sign stable — "
        f"early={early:+.4f} (N={is_adds.n_events}) "
        f"late={late:+.4f} (N={oos_adds.n_events}) (need same sign)"
    )

    placebo_null = abs(placebo.t_stat) < t_threshold
    reasons.append(
        f"{'PASS' if placebo_null else 'FAIL'}: placebo null — "
        f"mean={placebo.mean:+.4f} t={placebo.t_stat:+.2f} (need |t|<{t_threshold})"
    )

    passed = enough and sig and same_sign and placebo_null
    return GateVerdict(passed=passed, reasons=reasons)
