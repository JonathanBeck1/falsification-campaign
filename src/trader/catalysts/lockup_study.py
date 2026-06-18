"""Event study: do IPO lock-up expiries produce abnormal moves in the underlying?

This is the v1 (underlying-only) test pre-registered in
``research/lockup_expiry_study_preregistration.md``. It measures, in event time
relative to each lock-up expiry, the **market-adjusted** cumulative abnormal
return (CAR = stock return minus SPY return) and the **realized-vol ratio**
(post-event vol / pre-event baseline vol), then aggregates across events with a
t-stat, and checks the pre-registered gate against a **placebo** window and an
**out-of-sample** split.

Design choices (all pre-registered):

* t0 = the first trading day on or after the lock-up expiry date.
* Abnormal return uses a beta=1 market adjustment (stock minus SPY). Beta=1 is a
  deliberate, conservative simplification: recent high-beta IPOs would, if
  anything, have their *down* moves understated by it, so a negative CAR here is
  not an artifact of unmodeled beta.
* The placebo re-runs the identical computation with t0 shifted back 90 trading
  days, isolating the lock-up-specific effect from "recent IPOs just drift".

Everything here is pure and unit-tested on synthetic series; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from trader.research.event_study import sorted_close as _sorted_close
from trader.research.gate import t_stat as _t_stat

# Event-time windows, in trading days relative to t0 (inclusive ranges).
CAR_WINDOWS: dict[str, tuple[int, int]] = {
    "car_m5_m1": (-5, -1),   # pre-event run-up / drift-in
    "car_m1_p1": (-1, 1),    # the expiry itself
    "car_0_p5": (0, 5),
    "car_0_p10": (0, 10),
    "car_0_p21": (0, 21),    # the primary horizon (~1 month)
}
PRE_BASELINE = (-40, -20)    # vol baseline window
POST_WINDOW = (1, 21)        # realized-vol post window
LIQ_WINDOW = (-30, -10)      # dollar-volume liquidity window
NEED_LO = min(PRE_BASELINE[0], LIQ_WINDOW[0], min(w[0] for w in CAR_WINDOWS.values()))
NEED_HI = max(POST_WINDOW[1], max(w[1] for w in CAR_WINDOWS.values()))


@dataclass(frozen=True)
class EventMetrics:
    """Per-event abnormal-return and vol metrics in event time."""

    ticker: str
    event_date: date          # the lock-up expiry (calendar date) used as input
    t0_date: date             # the resolved t0 trading day
    car_m5_m1: float
    car_m1_p1: float
    car_0_p5: float
    car_0_p10: float
    car_0_p21: float
    vol_ratio: float          # post vol / pre-baseline vol (1.0 = unchanged)
    median_dollar_volume: float


@dataclass(frozen=True)
class WindowAgg:
    """Aggregated stats for one metric across events."""

    metric: str
    n: int
    mean: float
    median: float
    pct_negative: float
    t_stat: float             # vs 0 for CARs; vs 1 for vol_ratio


@dataclass(frozen=True)
class StudyResult:
    label: str
    n_events: int
    windows: dict[str, WindowAgg]
    vol_ratio: WindowAgg


def compute_event_metrics(
    close: pd.Series,
    volume: pd.Series,
    spy_close: pd.Series,
    event_date: date,
    *,
    offset_trading_days: int = 0,
) -> EventMetrics | None:
    """Compute one event's CARs and vol ratio, or ``None`` if data is insufficient.

    ``close``/``volume`` are the single stock's daily series (indexed by date);
    ``spy_close`` is SPY's daily close. ``offset_trading_days`` shifts t0 (used to
    build the placebo: pass -90). Returns ``None`` when the event lacks the full
    [NEED_LO, NEED_HI] trading-day window around t0.
    """

    close = _sorted_close(close)
    volume = volume.dropna().sort_index()
    volume.index = pd.DatetimeIndex(volume.index)
    if len(close) < (NEED_HI - NEED_LO + 2):
        return None

    dates = close.index
    pos = int(dates.searchsorted(pd.Timestamp(event_date), side="left"))
    t0 = pos + offset_trading_days
    if t0 < 0 or t0 >= len(dates):
        return None
    if t0 + NEED_LO < 0 or t0 + NEED_HI >= len(dates):
        return None

    ret = close.pct_change()
    spy = _sorted_close(spy_close).reindex(dates).ffill()
    ar = ret - spy.pct_change()  # market-adjusted abnormal return (beta=1)

    def _car(a: int, b: int) -> float:
        seg = ar.iloc[t0 + a : t0 + b + 1]
        return float(seg.sum())

    base = ret.iloc[t0 + PRE_BASELINE[0] : t0 + PRE_BASELINE[1] + 1]
    post = ret.iloc[t0 + POST_WINDOW[0] : t0 + POST_WINDOW[1] + 1]
    base_sd = float(base.std(ddof=1))
    post_sd = float(post.std(ddof=1))
    vol_ratio = (post_sd / base_sd) if base_sd > 0 else float("nan")

    vol_seg = volume.reindex(dates).iloc[t0 + LIQ_WINDOW[0] : t0 + LIQ_WINDOW[1] + 1]
    px_seg = close.iloc[t0 + LIQ_WINDOW[0] : t0 + LIQ_WINDOW[1] + 1]
    median_dollar_volume = float((px_seg * vol_seg).median())

    return EventMetrics(
        ticker=str(close.name) if close.name else "",
        event_date=event_date,
        t0_date=dates[t0].date(),
        car_m5_m1=_car(*CAR_WINDOWS["car_m5_m1"]),
        car_m1_p1=_car(*CAR_WINDOWS["car_m1_p1"]),
        car_0_p5=_car(*CAR_WINDOWS["car_0_p5"]),
        car_0_p10=_car(*CAR_WINDOWS["car_0_p10"]),
        car_0_p21=_car(*CAR_WINDOWS["car_0_p21"]),
        vol_ratio=vol_ratio,
        median_dollar_volume=median_dollar_volume,
    )


def _agg(metric: str, values: list[float], *, null: float = 0.0) -> WindowAgg:
    vals = [v for v in values if v == v]
    n = len(vals)
    if n == 0:
        return WindowAgg(metric=metric, n=0, mean=float("nan"), median=float("nan"), pct_negative=float("nan"), t_stat=0.0)
    s = pd.Series(vals)
    return WindowAgg(
        metric=metric,
        n=n,
        mean=float(s.mean()),
        median=float(s.median()),
        pct_negative=float((s < 0).mean()),
        t_stat=_t_stat(vals, null=null),
    )


def aggregate(metrics: list[EventMetrics], *, label: str) -> StudyResult:
    """Aggregate per-event metrics into mean/median/%neg/t-stat per window."""

    windows = {
        name: _agg(name, [getattr(m, name) for m in metrics]) for name in CAR_WINDOWS
    }
    vol = _agg("vol_ratio", [m.vol_ratio for m in metrics], null=1.0)
    return StudyResult(label=label, n_events=len(metrics), windows=windows, vol_ratio=vol)


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    real: StudyResult,
    placebo: StudyResult,
    oos_early: StudyResult,
    oos_late: StudyResult,
    *,
    min_events: int = 30,
    primary: str = "car_0_p21",
    car_t_threshold: float = 2.0,
    vol_ratio_threshold: float = 1.25,
    vol_t_threshold: float = 2.0,
) -> GateVerdict:
    """Apply the pre-registered v1 gate. Returns pass/fail + human reasons.

    ALL must hold: N>=min_events; (primary CAR negative with |t|>=2) OR (vol ratio
    >= threshold with t>=2); effect beats placebo on the primary CAR; effect keeps
    the same sign across the OOS split.
    """

    reasons: list[str] = []
    car = real.windows[primary]
    vol = real.vol_ratio

    enough_n = real.n_events >= min_events
    reasons.append(f"{'PASS' if enough_n else 'FAIL'}: N={real.n_events} (need >= {min_events})")

    car_sig = (car.mean < 0) and (abs(car.t_stat) >= car_t_threshold)
    vol_sig = (vol.mean >= vol_ratio_threshold) and (vol.t_stat >= vol_t_threshold)
    signal = car_sig or vol_sig
    reasons.append(
        f"{'PASS' if signal else 'FAIL'}: signal — {primary} mean={car.mean:+.4f} t={car.t_stat:+.2f} "
        f"(need <0 & |t|>={car_t_threshold}) OR vol_ratio mean={vol.mean:.3f} t={vol.t_stat:+.2f} "
        f"(need >={vol_ratio_threshold} & t>={vol_t_threshold})"
    )

    # Placebo: the real primary CAR must be more negative than the placebo's.
    p_car = placebo.windows[primary]
    beats_placebo = car.mean < p_car.mean
    reasons.append(
        f"{'PASS' if beats_placebo else 'FAIL'}: beats placebo — real {primary} mean={car.mean:+.4f} "
        f"vs placebo mean={p_car.mean:+.4f} (need real more negative)"
    )

    # OOS: same sign on the primary CAR across both sub-samples.
    early, late = oos_early.windows[primary].mean, oos_late.windows[primary].mean
    same_sign = (early < 0 and late < 0) or (early > 0 and late > 0)
    reasons.append(
        f"{'PASS' if same_sign else 'FAIL'}: OOS sign stable — early={early:+.4f} late={late:+.4f} (need same sign)"
    )

    passed = enough_n and signal and beats_placebo and same_sign
    return GateVerdict(passed=passed, reasons=reasons)
