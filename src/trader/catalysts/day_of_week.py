"""Calendar-effect study (T50): does SPY show a **Monday effect** (abnormally
negative Monday returns) and a **pre-holiday drift** (abnormally positive returns
on the last session before a market holiday) — and do either survive after costs
and out of sample?

Pre-registered in ``research/day_of_week_preregistration.md``. Falsify-first.

Honest prior: both are canonical anomalies that decayed / reversed after
publication and settlement reform. A day-of-week or pre-holiday **timing rule
trades essentially daily**, so a ~2 bps round trip dominates any few-bps gross
edge. We expect tiny gross effects and after-cost / OOS kills. A clean
"decayed and/or cost-eaten" finding is a win.

Design (all pre-registered):

* **Weekday cohorts (a):** each daily close-to-close return is labeled by the
  weekday it is realized on (Mon=0..Fri=4). PRIMARY contrast = Monday mean vs the
  pooled Tue-Fri mean.
* **Pre-holiday cohort (b):** the return realized on the last trading day before
  a market-closed weekday gap. A "holiday" is a weekday on which SPY did not
  trade (a gap in the daily index that is not a weekend). PRIMARY contrast =
  pre-holiday mean vs all non-pre-holiday days. Calendar-defined — no look-ahead.
* **Friction:** 2 bps round trip; after-cost is the only claimable metric.
* **Gate (per effect):** N>=30 (both IS/OOS halves N>=10); after-cost hypothesised
  sign with |t|>=2; IS/OOS sign stability; placebo (random pseudo-effect days
  abnormal ~0); too-good tripwire.

Everything in this module is **pure** — it operates on an in-memory price series,
does no I/O, and is unit-tested on synthetic data with injected effects. Only the
runner script touches yfinance.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from trader.research.event_study import sorted_close
from trader.research.gate import t_stat

# SPY round-trip cost for a one-day timing trade (buy prior close, sell labeled
# day's close): ~1 bp each way. A day-of-week rule pays this essentially daily.
ROUND_TRIP_COST = 0.0002
# A single daily SPY return beyond this magnitude is a data glitch (split/bad
# print), not a real move; the observation is dropped (counted, never hidden).
MAX_ABS_DAILY_RET = 0.30
# Weekday labels for reporting (Mon=0 .. Fri=4 / Sun-based pandas: see below).
WEEKDAY_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
MONDAY = 0


@dataclass(frozen=True)
class CohortStats:
    """Aggregate stats for a set of per-day return values (a cohort)."""

    label: str
    n: int
    mean: float
    median: float
    std: float
    pct_positive: float
    t_stat: float         # one-sample t vs null=0


@dataclass(frozen=True)
class AbnormalResult:
    """Abnormal return = cohort mean - matched non-cohort (pooled) baseline."""

    label: str
    n: int
    cohort_mean: float          # gross cohort mean
    baseline_mean: float        # pooled non-cohort mean
    abnormal_mean: float        # cohort_mean - baseline_mean (gross)
    after_cost_mean: float      # cohort_mean - ROUND_TRIP_COST
    after_cost_abnormal: float  # abnormal_mean - ROUND_TRIP_COST
    cohort_t: float             # one-sample t on per-day cohort returns (vs 0)
    abnormal_t: float           # two-sample-ish t on cohort vs baseline pools
    pct_positive: float


# --------------------------------------------------------------------------- #
# pure helpers — generic plumbing now lives in the shared homes:
#   _sorted_close → trader.research.event_study.sorted_close (byte-identical)
#   _t_stat(null=) → trader.research.gate.t_stat (ddof=1, 0.0-on-degenerate)
# _welch_t is deliberately NOT routed: the local form uses pd.Series.var(ddof=1),
# whose zero-variance result leaks a denormal residual (~1e-37) instead of exact
# 0.0, so the `denom == 0.0` guard does not trip and a constant-cohort vs
# constant-baseline contrast blows the t up to ~1e17. The shared gate.welch_t
# computes the variance manually (sum of squared deviations), gets an *exact* 0.0,
# and returns 0.0 — a different number on the degenerate path the unit tests
# exercise (test_*_abnormal_*_when_injected use constant cohorts). Routing it
# would move a number, so it stays local.
# --------------------------------------------------------------------------- #
def _welch_t(a: Sequence[float], b: Sequence[float]) -> float:
    """Welch two-sample t for mean(a) - mean(b), unequal variances. Pure.

    Kept local (not routed to ``trader.research.gate.welch_t``): the pandas-``var``
    path here is not behaviorally identical to the shared manual-variance form on
    the zero-variance / constant-cohort degenerate case (see note above).
    """

    av = [float(v) for v in a if v == v]
    bv = [float(v) for v in b if v == v]
    na, nb = len(av), len(bv)
    if na < 2 or nb < 2:
        return 0.0
    sa, sb = pd.Series(av), pd.Series(bv)
    va = float(sa.var(ddof=1)) / na
    vb = float(sb.var(ddof=1)) / nb
    denom = math.sqrt(va + vb)
    if denom == 0.0:
        return 0.0
    return float((sa.mean() - sb.mean()) / denom)


def summarize(values: Sequence[float], *, label: str) -> CohortStats:
    """Mean/median/std/%pos/one-sample-t for a list of per-day values. Pure."""

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
        t_stat=t_stat(vals),
    )


# --------------------------------------------------------------------------- #
# return / label construction (pure, calendar-defined)
# --------------------------------------------------------------------------- #
def daily_returns(close: pd.Series) -> pd.Series:
    """Close-to-close returns, glitch-filtered (|r| > MAX_ABS_DAILY_RET dropped).

    Returns a Series indexed by the date on which each return is *realized*. Pure.
    """

    close = sorted_close(close)
    ret = close.pct_change().iloc[1:]
    ret = ret[ret.abs() <= MAX_ABS_DAILY_RET]
    return ret.dropna()


def pre_holiday_mask(index: pd.DatetimeIndex) -> pd.Series:
    """Boolean mask (aligned to ``index``) flagging each trading day whose *next*
    calendar weekday is NOT a trading day (a market holiday) — i.e. the last
    session before a holiday gap.

    A "holiday" = a weekday absent from the trading index. The gap to the next
    trading day spanning at least one missing weekday marks the current day as
    pre-holiday. Weekend-only gaps (Fri->Mon) are NOT pre-holiday. Calendar-
    defined: uses only which days the market was open, no price/future info. Pure.
    """

    idx = pd.DatetimeIndex(index).sort_values()
    flags = []
    for i in range(len(idx)):
        if i == len(idx) - 1:
            flags.append(False)  # no known next session; cannot label
            continue
        cur = idx[i]
        nxt = idx[i + 1]
        # Count missing *weekdays* strictly between cur and nxt.
        gap_days = pd.bdate_range(cur + pd.Timedelta(days=1), nxt - pd.Timedelta(days=1))
        flags.append(len(gap_days) > 0)
    return pd.Series(flags, index=idx, name="pre_holiday")


# --------------------------------------------------------------------------- #
# weekday + pre-holiday aggregation (pure)
# --------------------------------------------------------------------------- #
def weekday_cohorts(returns: pd.Series) -> dict[int, CohortStats]:
    """One CohortStats per weekday (Mon=0..Fri=4) over realized returns. Pure."""

    out: dict[int, CohortStats] = {}
    wd = returns.index.weekday
    for w in range(5):
        vals = [float(v) for v in returns[wd == w].tolist()]
        out[w] = summarize(vals, label=WEEKDAY_NAMES.get(w, str(w)))
    return out


def monday_abnormal(returns: pd.Series, *, cost: float = ROUND_TRIP_COST) -> AbnormalResult:
    """Monday cohort vs pooled Tue-Fri baseline (the PRIMARY weekday contrast).

    Hypothesis sign: Monday mean NEGATIVE relative to the rest of the week. Pure.
    """

    wd = returns.index.weekday
    mon = [float(v) for v in returns[wd == MONDAY].tolist()]
    rest = [float(v) for v in returns[(wd != MONDAY) & (wd <= 4)].tolist()]
    return _abnormal("monday", mon, rest, cost=cost)


def pre_holiday_abnormal(
    returns: pd.Series, *, cost: float = ROUND_TRIP_COST
) -> AbnormalResult:
    """Pre-holiday cohort vs pooled non-pre-holiday baseline (PRIMARY (b) contrast).

    Hypothesis sign: pre-holiday mean POSITIVE relative to ordinary days. Pure.
    """

    mask = pre_holiday_mask(returns.index)
    mask = mask.reindex(returns.index).fillna(False)
    pre = [float(v) for v in returns[mask.to_numpy()].tolist()]
    other = [float(v) for v in returns[~mask.to_numpy()].tolist()]
    return _abnormal("pre_holiday", pre, other, cost=cost)


def _abnormal(
    label: str,
    cohort: Sequence[float],
    baseline: Sequence[float],
    *,
    cost: float,
) -> AbnormalResult:
    coh = summarize(cohort, label=label)
    base = summarize(baseline, label=f"{label}_baseline")
    abn = coh.mean - base.mean if coh.n and base.n else float("nan")
    return AbnormalResult(
        label=label,
        n=coh.n,
        cohort_mean=coh.mean,
        baseline_mean=base.mean,
        abnormal_mean=abn,
        after_cost_mean=coh.mean - cost if coh.n else float("nan"),
        after_cost_abnormal=abn - cost if abn == abn else float("nan"),
        cohort_t=coh.t_stat,
        abnormal_t=_welch_t(cohort, baseline),
        pct_positive=coh.pct_positive,
    )


def split_is_oos(returns: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Chronological early/late half split of realized returns. Pure."""

    r = returns.sort_index()
    mid = len(r) // 2
    return r.iloc[:mid], r.iloc[mid:]


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    full: AbnormalResult,
    is_cohort: CohortStats,
    oos_cohort: CohortStats,
    placebo_abnormal_t95: float,
    *,
    hypothesis_sign: int,
    min_n: int = 30,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T50 per-effect gate (ALL must hold):

    N>=min_n (both IS/OOS halves N>=10); AFTER-COST cohort mean in the
    hypothesised direction with abnormal |t|>=t_threshold; IS/OOS cohort means
    same sign (both N>=10); the abnormal |t| exceeds the placebo 95th-pct |t|.

    ``hypothesis_sign``: -1 for the Monday effect (expect negative), +1 for the
    pre-holiday drift (expect positive). Each line is reported PASS/FAIL.
    """

    reasons: list[str] = []

    enough = full.n >= min_n
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={full.n} (need >= {min_n})")

    # After-cost: the cohort mean shifted by one round trip, in the right direction.
    signed_after_cost = full.after_cost_mean * hypothesis_sign
    sig = (signed_after_cost > 0) and (abs(full.abnormal_t) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: after-cost signal — net mean="
        f"{full.after_cost_mean:+.6f} (sign want {'+' if hypothesis_sign > 0 else '-'}) "
        f"abnormal |t|={abs(full.abnormal_t):.2f} (need right sign & |t|>={t_threshold})"
    )

    is_n_ok = is_cohort.n >= 10 and oos_cohort.n >= 10
    same_sign = (is_cohort.mean > 0 and oos_cohort.mean > 0) or (
        is_cohort.mean < 0 and oos_cohort.mean < 0
    )
    oos_ok = is_n_ok and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stable — IS={is_cohort.mean:+.6f} "
        f"(N={is_cohort.n}) OOS={oos_cohort.mean:+.6f} (N={oos_cohort.n}) "
        f"(need same sign, both N>=10)"
    )

    placebo_ok = abs(full.abnormal_t) > abs(placebo_abnormal_t95)
    reasons.append(
        f"{'PASS' if placebo_ok else 'FAIL'}: placebo — real abnormal |t|="
        f"{abs(full.abnormal_t):.2f} vs placebo 95th-pct |t|={abs(placebo_abnormal_t95):.2f} "
        f"(need real > placebo)"
    )

    return GateVerdict(
        passed=enough and sig and oos_ok and placebo_ok, reasons=reasons
    )
