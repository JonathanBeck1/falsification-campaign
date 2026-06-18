"""Event study (T47): does SPY drift UP in the ~24h before a scheduled FOMC
announcement (the Lucca-Moench 2015 "Pre-FOMC Announcement Drift") — and does it
survive after costs and out of sample?

Pre-registered in ``research/fomc_drift_preregistration.md``. Falsify-first.

Honest prior: the anomaly was large and famous pre-2015 but is widely reported to
have **decayed** once publicized. We expect a positive in-sample drift, a weak or
null out-of-sample one, and a thin/negative net after a 2 bps SPY round trip. A
clean decay finding is a win.

Design (all pre-registered):

* Event list = scheduled FOMC announcement (2nd/decision) days, knowable ex-ante
  from the published Fed calendar (hardcoded in the runner; see pre-reg §10).
* For each event day D, the **pre-FOMC return** is SPY's close-to-close return on
  D-1 (the session entirely before the 2pm-ET statement on D). This is the daily
  proxy for the Lucca-Moench 24h-before window.
* **Abnormal** pre-FOMC return = per-event D-1 return; the cohort mean is compared
  to the mean SPY return on **non-event days** (>3 trading days from any event),
  a pooled, matched-by-construction baseline.
* Gate: N>=30; after-cost (2 bps) pre-FOMC |t|>=2; OOS sign stability (IS vs OOS);
  placebo (random pseudo-events drift ~0); too-good tripwire.

Everything in this module is **pure** — it operates on an in-memory price series
and a list of event dates, does no I/O, and is unit-tested on synthetic data with
an injected pre-event drift. Only the runner script touches yfinance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

from trader.research.event_study import sorted_close as _sorted_close
from trader.research.gate import t_stat as _t_stat

# Trading-day offsets, relative to the announcement day D (which is event index 0).
PRE_FOMC = -1  # the session before the statement — the PRIMARY drift window
# Days within +/- this many trading days of any event are excluded from the
# non-event baseline so the control cannot inherit event-window drift.
BASELINE_EXCLUSION = 3
# SPY round-trip cost (buy D-2 close, sell D-1 close): ~1 bp each way.
ROUND_TRIP_COST = 0.0002
# A single daily SPY return beyond this magnitude is a data glitch (split/bad
# print), not a real move; the event is dropped (counted, never hidden).
MAX_ABS_DAILY_RET = 0.30


@dataclass(frozen=True)
class EventReturn:
    """One scheduled FOMC event's pre-announcement returns, in event time."""

    event_date: date      # the scheduled announcement (2nd) day requested
    d_date: date          # resolved announcement trading day D
    pre_fomc: float       # D-1 close-to-close return (PRIMARY)
    announce: float       # D close-to-close return (reaction; reported, not claimed)
    pre2: float           # cumulative D-2..D-1 (wider pre-window robustness)


@dataclass(frozen=True)
class CohortStats:
    """Aggregate stats for a set of per-event values (a window column)."""

    label: str
    n: int
    mean: float
    median: float
    std: float
    pct_positive: float
    t_stat: float         # one-sample t vs null=0


# --------------------------------------------------------------------------- #
# pure helpers
#
# ``_sorted_close`` and ``_t_stat`` are now imported (aliased) from the shared
# homes — ``trader.research.event_study.sorted_close`` and
# ``trader.research.gate.t_stat`` — which are behaviorally identical to the
# former local copies (same dropna→sort→DatetimeIndex; same ddof=1 t-stat with
# 0.0 on N<2 / zero-variance; same ``null=`` keyword). All returns reaching the
# t-stat here are pre-filtered to ``|ret| <= MAX_ABS_DAILY_RET`` and finite.
# --------------------------------------------------------------------------- #
def summarize(values: Sequence[float], *, label: str) -> CohortStats:
    """Mean/median/std/%pos/one-sample-t for a list of per-event values. Pure."""

    vals = [float(v) for v in values if v == v]
    n = len(vals)
    if n == 0:
        return CohortStats(label, 0, float("nan"), float("nan"), float("nan"), float("nan"), 0.0)
    s = pd.Series(vals)
    return CohortStats(
        label=label,
        n=n,
        mean=float(s.mean()),
        median=float(s.median()),
        std=float(s.std(ddof=1)) if n > 1 else 0.0,
        pct_positive=float((s > 0).mean()),
        t_stat=_t_stat(vals),
    )


def compute_event_return(
    close: pd.Series,
    event_date: date,
) -> EventReturn | None:
    """Compute one scheduled FOMC event's pre-announcement returns, or ``None``.

    ``close`` is SPY's auto-adjusted daily close. D = first trading day on/after
    ``event_date``. Returns ``None`` if the ``[D-2, D]`` window is not fully
    present or any single-day return in it is an absurd glitch.
    """

    close = _sorted_close(close)
    if len(close) < 4:
        return None
    dates = close.index
    d_pos = int(dates.searchsorted(pd.Timestamp(event_date), side="left"))
    if d_pos >= len(dates):
        return None  # event after the series ends
    # Need D-2, D-1, D and the bar before D-2 to form a D-2 return.
    if d_pos - 2 < 1 or d_pos >= len(dates):
        return None

    ret = close.pct_change()
    r_dm2 = float(ret.iloc[d_pos - 2])
    r_dm1 = float(ret.iloc[d_pos - 1])
    r_d = float(ret.iloc[d_pos])
    if any(abs(r) > MAX_ABS_DAILY_RET for r in (r_dm2, r_dm1, r_d)):
        return None

    return EventReturn(
        event_date=event_date,
        d_date=dates[d_pos].date(),
        pre_fomc=r_dm1,
        announce=r_d,
        pre2=r_dm2 + r_dm1,
    )


def non_event_baseline_mean(
    close: pd.Series,
    event_dates: Sequence[date],
    *,
    exclusion: int = BASELINE_EXCLUSION,
) -> CohortStats:
    """Mean SPY close-to-close return over trading days NOT within ``exclusion``
    trading days of any scheduled FOMC announcement day. The pooled baseline. Pure.
    """

    close = _sorted_close(close)
    ret = close.pct_change()
    dates = close.index
    n = len(dates)
    excluded: set[int] = set()
    for ev in event_dates:
        pos = int(dates.searchsorted(pd.Timestamp(ev), side="left"))
        if pos >= n:
            continue
        for k in range(pos - exclusion, pos + exclusion + 1):
            if 0 <= k < n:
                excluded.add(k)
    vals = [
        float(ret.iloc[i])
        for i in range(1, n)  # i>=1: pct_change at 0 is NaN
        if i not in excluded and abs(float(ret.iloc[i])) <= MAX_ABS_DAILY_RET
        and ret.iloc[i] == ret.iloc[i]
    ]
    return summarize(vals, label="non_event_baseline")


# --------------------------------------------------------------------------- #
# abnormal return + gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AbnormalResult:
    """Pre-FOMC abnormal return = cohort pre_fomc mean - non-event baseline mean."""

    n: int
    cohort_mean: float          # gross pre_fomc mean
    baseline_mean: float
    abnormal_mean: float        # cohort_mean - baseline_mean (gross)
    after_cost_mean: float      # cohort_mean - ROUND_TRIP_COST
    after_cost_abnormal: float  # abnormal_mean - ROUND_TRIP_COST
    t_stat: float               # one-sample t on per-event pre_fomc (vs 0)
    pct_positive: float


def abnormal_pre_fomc(
    events: Sequence[EventReturn],
    baseline: CohortStats,
    *,
    cost: float = ROUND_TRIP_COST,
) -> AbnormalResult:
    """Combine per-event pre_fomc returns with the pooled baseline into the
    abnormal-return result. Pure.
    """

    pre = summarize([e.pre_fomc for e in events], label="pre_fomc")
    abn = pre.mean - baseline.mean if pre.n and baseline.n else float("nan")
    return AbnormalResult(
        n=pre.n,
        cohort_mean=pre.mean,
        baseline_mean=baseline.mean,
        abnormal_mean=abn,
        after_cost_mean=pre.mean - cost if pre.n else float("nan"),
        after_cost_abnormal=abn - cost if abn == abn else float("nan"),
        t_stat=pre.t_stat,
        pct_positive=pre.pct_positive,
    )


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    full: AbnormalResult,
    is_pre: CohortStats,
    oos_pre: CohortStats,
    placebo_abnormal_t: float,
    real_t: float,
    *,
    min_events: int = 30,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T47 gate (ALL must hold):

    N>=min_events; AFTER-COST pre-FOMC positive with |t|>=t_threshold; IS/OOS
    pre-FOMC means same sign (both N>=10); the real |t| exceeds the placebo |t|
    band (placebo drift ~0). Each line is reported PASS/FAIL.
    """

    reasons: list[str] = []

    enough = full.n >= min_events
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={full.n} (need >= {min_events})")

    sig = (full.after_cost_mean > 0) and (abs(full.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: after-cost signal — pre_fomc net mean="
        f"{full.after_cost_mean:+.5f} t={full.t_stat:+.2f} (need >0 & |t|>={t_threshold})"
    )

    is_n_ok = is_pre.n >= 10 and oos_pre.n >= 10
    same_sign = (is_pre.mean > 0 and oos_pre.mean > 0) or (
        is_pre.mean < 0 and oos_pre.mean < 0
    )
    oos_ok = is_n_ok and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stable — IS={is_pre.mean:+.5f} "
        f"(N={is_pre.n}) OOS={oos_pre.mean:+.5f} (N={oos_pre.n}) "
        f"(need same sign, both N>=10)"
    )

    placebo_ok = abs(real_t) > abs(placebo_abnormal_t)
    reasons.append(
        f"{'PASS' if placebo_ok else 'FAIL'}: placebo — real |t|={abs(real_t):.2f} "
        f"vs placebo 95th-pct |t|={abs(placebo_abnormal_t):.2f} (need real > placebo)"
    )

    return GateVerdict(
        passed=enough and sig and oos_ok and placebo_ok, reasons=reasons
    )
