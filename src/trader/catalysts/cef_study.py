"""Event study: does following Saba's 13D into a CEF earn capturable excess return?

Pre-registered in ``research/cef_activist_study_preregistration.md``. The thesis:
an activist (Saba) discloses a CEF stake via SC 13D, the discount-to-NAV narrows
toward a tender/open-ending catalyst. The sharp question is whether a *follower*
— who can only act once the 13D is public — captures any of it, or whether it is
already priced in the pre-disclosure run-up and the announcement-day pop.

Metric is NAV-free: total return of the target CEF minus a broad-CEF benchmark
(PCEF), which nets out CEF-market beta and general discount moves without needing
per-fund NAV. Effect is decomposed into:

* ``exc_pre``  — excess over [-126,-1]: pre-disclosure run-up (NOT capturable).
* ``exc_ann``  — excess over [-1,+1]: announcement pop (mostly not capturable).
* ``exc_1m/3m/6m/12m`` — excess from **entry = t0+1** (day after the public
  filing) forward — the **follower-capturable** drift. This is what matters.

Pure and unit-tested on synthetic series; no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

# Forward windows: (start_pos, end_pos) in trading days relative to t0.
# Entry is t0+1 (the day after the filing is public).
FWD_WINDOWS: dict[str, tuple[int, int]] = {
    "exc_1m": (1, 22),
    "exc_3m": (1, 64),
    "exc_6m": (1, 127),
    "exc_12m": (1, 253),
}
PRE_WINDOW = (-126, -1)
ANN_WINDOW = (-1, 1)
NEED_LO = PRE_WINDOW[0]
# Require only through the PRIMARY (6m) horizon so recent campaigns aren't
# dropped for lacking a full 12m window; longer windows return NaN when unelapsed.
NEED_HI = FWD_WINDOWS["exc_6m"][1]


@dataclass(frozen=True)
class CefEventMetrics:
    ticker: str
    event_date: date
    t0_date: date
    exc_pre: float
    exc_ann: float
    exc_1m: float
    exc_3m: float
    exc_6m: float
    exc_12m: float


@dataclass(frozen=True)
class WindowStat:
    metric: str
    n: int
    mean: float
    median: float
    pct_positive: float
    t_stat: float


@dataclass(frozen=True)
class CefStudyResult:
    label: str
    n_events: int
    stats: dict[str, WindowStat]


def _sorted(series: pd.Series) -> pd.Series:
    s = series.dropna().sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def compute_cef_event(
    target_close: pd.Series,
    bench_close: pd.Series,
    event_date: date,
) -> CefEventMetrics | None:
    """Forward excess returns (target minus benchmark) around a 13D, or None."""

    close = _sorted(target_close)
    if len(close) < (NEED_HI - NEED_LO + 2):
        return None
    dates = close.index
    t0 = int(dates.searchsorted(pd.Timestamp(event_date), side="left"))
    if t0 < 0 or t0 >= len(dates):
        return None
    if t0 + NEED_LO < 0 or t0 + NEED_HI >= len(dates):
        return None

    bench = _sorted(bench_close).reindex(dates).ffill()

    n = len(dates)

    def _ret(s: pd.Series, a: int, b: int) -> float:
        if t0 + a < 0 or t0 + b >= n:        # window not fully elapsed → NaN
            return float("nan")
        pa, pb = s.iloc[t0 + a], s.iloc[t0 + b]
        if pa is None or pa == 0 or pa != pa:
            return float("nan")
        return float(pb / pa - 1.0)

    def _exc(a: int, b: int) -> float:
        return _ret(close, a, b) - _ret(bench, a, b)

    return CefEventMetrics(
        ticker=str(close.name) if close.name else "",
        event_date=event_date,
        t0_date=dates[t0].date(),
        exc_pre=_exc(*PRE_WINDOW),
        exc_ann=_exc(*ANN_WINDOW),
        exc_1m=_exc(*FWD_WINDOWS["exc_1m"]),
        exc_3m=_exc(*FWD_WINDOWS["exc_3m"]),
        exc_6m=_exc(*FWD_WINDOWS["exc_6m"]),
        exc_12m=_exc(*FWD_WINDOWS["exc_12m"]),
    )


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


def _stat(metric: str, values: list[float]) -> WindowStat:
    vals = [v for v in values if v == v]
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
        t_stat=_t_stat(vals),
    )


_ALL_METRICS = ["exc_pre", "exc_ann", "exc_1m", "exc_3m", "exc_6m", "exc_12m"]


def aggregate(metrics: list[CefEventMetrics], *, label: str) -> CefStudyResult:
    stats = {m: _stat(m, [getattr(e, m) for e in metrics]) for m in _ALL_METRICS}
    return CefStudyResult(label=label, n_events=len(metrics), stats=stats)


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    real: CefStudyResult,
    oos_early: CefStudyResult,
    oos_late: CefStudyResult,
    *,
    min_events: int = 30,
    primary: str = "exc_6m",
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered gate: capturable 6m excess > 0 with |t|>=2, exceeding the
    pre-disclosure run-up, same sign OOS."""

    reasons: list[str] = []
    cap = real.stats[primary]
    pre = real.stats["exc_pre"]

    enough = real.n_events >= min_events
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={real.n_events} (need >= {min_events})")

    sig = (cap.mean > 0) and (cap.t_stat >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: capturable {primary} mean={cap.mean:+.4f} t={cap.t_stat:+.2f} "
        f"(need >0 & t>={t_threshold})"
    )

    beats_pre = cap.mean > pre.mean
    reasons.append(
        f"{'PASS' if beats_pre else 'FAIL'}: drift exceeds pre-run-up — {primary} mean={cap.mean:+.4f} "
        f"vs exc_pre mean={pre.mean:+.4f}"
    )

    e, latev = oos_early.stats[primary].mean, oos_late.stats[primary].mean
    same_sign = (e > 0 and latev > 0) or (e < 0 and latev < 0)
    reasons.append(
        f"{'PASS' if same_sign else 'FAIL'}: OOS sign stable — early={e:+.4f} late={latev:+.4f}"
    )

    return GateVerdict(passed=enough and sig and beats_pre and same_sign, reasons=reasons)
