"""Campaign test T42 — Spin-off post-event drift.

Pre-registered in ``research/spinoff_drift_preregistration.md``. Falsify-first.
The PREDICTED outcome is a decayed null.

Hypothesis: the spun-off company ("spinco") earns a positive after-cost
market-adjusted CAR over the first ~1-3 months of independent regular-way
trading, because forced/indiscriminate index-fund and mandate-driven selling at
the distribution temporarily underprices it (the Greenblatt / Cusatis-Miles-
Woolridge spin-off anomaly). Mechanism: price-insensitive forced selling into a
newly listed, under-covered name. Honest prior: the effect was large pre-2000
but most recent evidence (McConnell et al.) says it decayed once anticipated and
arbitraged (spin-off ETFs, index fast-tracking) -- we expect a KILL.

Universe: SEC Form 10-12B filers (the registration a spin-off uses), deduped to
the earliest 10-12B per CIK, 2015-2025. Registration-based, so it INCLUDES
spincos that later delisted / went bankrupt (e.g. Armstrong Flooring) --
survivorship is captured by construction. t0 = first regular-way trading day
(first yfinance day); the PRIMARY CAR is measured strictly forward from t0+1 (the
entry is the t0 close, a transactable price), so cohort membership uses no return
inside the measurement window (the discipline whose absence killed T07/PEAD).

Everything here is **pure**: it operates on in-memory price series and an event
list and does no I/O. Only the runner script touches the network (EDGAR +
yfinance).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

import pandas as pd

from trader.research.event_study import sorted_close as _sorted_close
from trader.research.gate import t_stat as _t_stat

# Event-time CAR windows, trading days relative to t0 (= first regular-way day).
# The PRIMARY is the forward ~1-month window measured strictly after t0.
CAR_WINDOWS: dict[str, tuple[int, int]] = {
    "car_p1_p21": (1, 21),   # PRIMARY: ~1 month forward drift, entry at t0 close
    "car_p1_p63": (1, 63),   # ~3 month (Greenblatt holding horizon)
    "car_p0_p21": (0, 21),   # includes the first-day move (robustness only)
}
PRIMARY_WINDOW = "car_p1_p21"
NEED_LO = min(w[0] for w in CAR_WINDOWS.values())
NEED_HI = max(w[1] for w in CAR_WINDOWS.values())

# A single-day market-adjusted return beyond this magnitude is, for a newly
# listed spinco, almost certainly a yfinance data glitch (unadjusted split / bad
# near-zero or when-issued print), not a real flow move. The event is dropped
# (counted, never hidden). Matches the house 75% guard used in T39.
MAX_ABS_DAILY_AR = 0.75

# Round-trip friction for a newly listed spinco (pre-reg section 6): 20 bps,
# double the 10 bps used for liquid S&P constituents (wider, thinner names).
ROUND_TRIP_COST = 0.0020

# IS / OOS split boundary (pre-registered): IS = first-trade year <= 2019.
OOS_SPLIT_YEAR = 2020


# --------------------------------------------------------------------------- #
# Event list
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SpinoffEvent:
    """One spinco: ticker, the 10-12B filing date, and (resolved by the runner)
    the first regular-way trading date. ``first_trade`` may be ``None`` before
    price resolution; the pure CAR math takes the date directly."""

    ticker: str
    cik: str
    filing_date: date
    name: str


# --------------------------------------------------------------------------- #
# CAR math (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EventMetrics:
    """Per-spinco market-adjusted forward CARs in event time (anchored on t0 =
    first regular-way trading day)."""

    ticker: str
    first_trade_date: date
    car_p1_p21: float
    car_p1_p63: float
    car_p0_p21: float


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

    close = _sorted_close(close)
    ret = close.pct_change()
    spy = _sorted_close(spy_close).reindex(close.index).ffill()
    return ret - spy.pct_change()


def compute_event_metrics(
    close: pd.Series,
    spy_close: pd.Series,
    *,
    first_trade_index: int = 0,
) -> EventMetrics | None:
    """Compute one spinco's forward market-adjusted CARs anchored at t0.

    t0 is the row at ``first_trade_index`` in the (sorted) ``close`` series --
    by default the first available trading day, i.e. the first regular-way day.
    The PRIMARY window [t0+1, t0+21] is measured strictly AFTER t0 (entry is the
    t0 close). Returns ``None`` if the full [NEED_LO, NEED_HI] forward window is
    not present (thin/short history) or if any single-day AR in any window is an
    absurd glitch.
    """

    close = _sorted_close(close)
    dates = close.index
    t0 = first_trade_index
    if t0 < 0 or t0 >= len(dates):
        return None
    # need t0+NEED_HI to exist, and t0+NEED_LO >= 0; plus one row for pct_change.
    if t0 + NEED_HI >= len(dates) or t0 + NEED_LO < 0:
        return None

    ar = _abnormal_return(close, spy_close)

    # glitch guard over the union of all windows touched.
    span = ar.iloc[t0 + NEED_LO : t0 + NEED_HI + 1]
    if (span.abs() > MAX_ABS_DAILY_AR).any():
        return None

    def _car(a: int, b: int) -> float:
        return float(ar.iloc[t0 + a : t0 + b + 1].sum())

    return EventMetrics(
        ticker=str(close.name) if close.name else "",
        first_trade_date=dates[t0].date(),
        car_p1_p21=_car(*CAR_WINDOWS["car_p1_p21"]),
        car_p1_p63=_car(*CAR_WINDOWS["car_p1_p63"]),
        car_p0_p21=_car(*CAR_WINDOWS["car_p0_p21"]),
    )


def placebo_cars(
    close: pd.Series,
    spy_close: pd.Series,
    *,
    window_len: int,
    n_draws: int,
    rng: random.Random,
    min_start: int = 1,
) -> list[float]:
    """Random non-event CARs of the same width on the SAME name (placebo control).

    Draws ``n_draws`` random ``window_len``-day windows from the name's own
    abnormal-return series (starting no earlier than ``min_start``) and returns
    each window's CAR. A real forced-selling edge must NOT appear in these random
    windows. Pure (rng injected). Glitch windows are skipped (counted as fewer
    draws), never hidden.
    """

    ar = _abnormal_return(close, spy_close).dropna()
    n = len(ar)
    if n < window_len + 1 or min_start >= n - window_len:
        return []
    out: list[float] = []
    hi = n - window_len
    for _ in range(n_draws):
        start = rng.randint(min_start, hi)
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
        t_stat=_t_stat(vals),
    )


def aggregate(metrics: list[EventMetrics], *, label: str) -> StudyResult:
    """Aggregate per-spinco CARs into mean/median/%pos/t-stat per window. Pure."""

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
    """Partition spincos into IS (first-trade year < split_year) and OOS halves."""

    is_ = [m for m in metrics if m.first_trade_date.year < split_year]
    oos = [m for m in metrics if m.first_trade_date.year >= split_year]
    return is_, oos


def drop_top_contributors(
    metrics: list[EventMetrics], *, window: str = PRIMARY_WINDOW, k: int = 5
) -> StudyResult:
    """Remove the ``k`` largest-magnitude contributors and re-aggregate.

    A real edge survives losing its top-5 names; an artifact driven by a few
    outliers collapses. Pure. (Pre-reg kill criterion: <5 names drive it.)
    """

    ranked = sorted(metrics, key=lambda m: abs(getattr(m, window)), reverse=True)
    kept = ranked[k:]
    return aggregate(kept, label=f"drop_top{k}")


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    cohort: StudyResult,
    is_cohort: StudyResult,
    oos_cohort: StudyResult,
    placebo: WindowAgg,
    *,
    min_events: int = 30,
    t_threshold: float = 2.0,
    round_trip: float = ROUND_TRIP_COST,
) -> GateVerdict:
    """Pre-registered spinco gate (ALL must hold), PRIMARY = [t0+1, t0+21].

    N>=min_events; AFTER-COST primary CAR positive with |t|>=t_threshold; IS/OOS
    same sign (both N>=10 checked by the runner's report); placebo null AND
    cohort mean exceeds placebo mean. The decay comparison is reported by the
    runner regardless of pass/fail.
    """

    reasons: list[str] = []
    car = cohort.windows[PRIMARY_WINDOW]
    net = after_cost_mean(car, round_trip=round_trip)

    enough = cohort.n_events >= min_events
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: N={cohort.n_events} (need >= {min_events})"
    )

    sig = (net > 0) and (abs(car.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: after-cost signal — {PRIMARY_WINDOW} "
        f"net={net:+.4f} (gross={car.mean:+.4f}) t={car.t_stat:+.2f} "
        f"(need net>0 & |t|>={t_threshold})"
    )

    early = is_cohort.windows[PRIMARY_WINDOW].mean
    late = oos_cohort.windows[PRIMARY_WINDOW].mean
    # Enforce the N>=10-per-half floor IN the gate (it was previously delegated to
    # "the runner's report"); a same-sign coincidence on a thin half is not OOS
    # stability. Matches the shared gate + sibling event studies.
    enough_oos = is_cohort.n_events >= 10 and oos_cohort.n_events >= 10
    same_sign = (early > 0 and late > 0) or (early < 0 and late < 0)
    oos_ok = enough_oos and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stable — "
        f"early={early:+.4f} (N={is_cohort.n_events}) "
        f"late={late:+.4f} (N={oos_cohort.n_events}) (need same sign & both N>=10)"
    )

    placebo_null = abs(placebo.t_stat) < t_threshold
    beats = car.mean > placebo.mean
    reasons.append(
        f"{'PASS' if (placebo_null and beats) else 'FAIL'}: placebo control — "
        f"placebo mean={placebo.mean:+.4f} t={placebo.t_stat:+.2f} "
        f"(need |t|<{t_threshold} AND cohort {car.mean:+.4f} > placebo)"
    )

    passed = enough and sig and oos_ok and placebo_null and beats
    return GateVerdict(passed=passed, reasons=reasons)
