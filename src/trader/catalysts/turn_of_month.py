"""Calendar-effect study (T48): are SPY daily returns abnormally high in the
turn-of-month (TOM) window — the last trading day of a month through the first
three trading days of the next — vs the rest of the month (ROM)?

Pre-registered in ``research/turn_of_month_preregistration.md``. Falsify-first.

Honest prior: the TOM effect (Ariel 1987; Lakonishok-Smidt 1988) is one of the
most-published seasonal anomalies and is widely reported to have **decayed**. We
expect a positive, possibly significant in-sample difference and a weaker/null
out-of-sample one, with no tradeable after-cost edge. A clean decay finding is a
win.

Design (all pre-registered):

* The TOM window for each calendar month-turn = {LDOM, +1, +2, +3} where LDOM is
  the **last trading day of a calendar month** and +1/+2/+3 are the first three
  trading days of the next month — 4 trading days per turn.
* Membership is **calendar-defined**: it depends only on each date's position in
  the trading-day index, never on any return/price. No look-ahead (pre-reg §5).
* PRIMARY statistic = ``mean(TOM daily ret) - mean(ROM daily ret)`` with a Welch
  two-sample t-test on the two daily-return populations.
* Gate: IS/OOS TOM N>=100; after-cost (0.5 bp/TOM-day) difference positive with
  Welch |t|>=2; OOS sign stability (IS vs OOS); placebo (random pseudo-turn
  windows difference ~0); too-good tripwire.

Everything here is **pure** — it operates on an in-memory daily-return series
indexed by date, does no I/O, and is unit-tested on synthetic data with an
injected TOM bump. Only the runner script touches yfinance.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

# The TOM window, in trading-day offsets relative to a month boundary:
#   -1 = last trading day of the calendar month (LDOM)
#   +1,+2,+3 = first three trading days of the next calendar month
TOM_TRADING_DAYS = (-1, 1, 2, 3)
# Per-TOM-day amortized friction: a long-TOM rule does ~1 round trip per turn
# (~2 bps SPY) spread over the 4 TOM days -> 0.5 bp per TOM day.
PER_DAY_COST = 0.00005
# A single daily return beyond this magnitude is a data glitch (split/bad print).
MAX_ABS_DAILY_RET = 0.30


@dataclass(frozen=True)
class WindowStats:
    """Aggregate stats for one window's daily-return population."""

    label: str
    n: int
    mean: float
    median: float
    std: float
    pct_positive: float
    t_stat: float  # one-sample t vs null=0


@dataclass(frozen=True)
class TomResult:
    """TOM vs ROM comparison on a daily-return series."""

    tom: WindowStats
    rom: WindowStats
    diff: float            # gross TOM mean - ROM mean (per-day abnormal return)
    after_cost_diff: float  # diff - PER_DAY_COST
    welch_t: float         # two-sample Welch t on TOM vs ROM daily returns


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def _clean_returns(returns: pd.Series) -> pd.Series:
    """Sort by date, drop NaN, and drop glitch-magnitude returns. Pure."""

    s = returns.dropna()
    s = s[s.abs() <= MAX_ABS_DAILY_RET]
    s = s.sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def _one_sample_t(vals: Sequence[float], *, null: float = 0.0) -> float:
    v = np.asarray([float(x) for x in vals if x == x], dtype=float)
    if v.size < 2:
        return 0.0
    sd = float(v.std(ddof=1))
    if sd == 0.0:
        return 0.0
    return float((v.mean() - null) / (sd / math.sqrt(v.size)))


def _welch_t(left: Sequence[float], right: Sequence[float]) -> float:
    a = np.asarray([float(x) for x in left if x == x], dtype=float)
    b = np.asarray([float(x) for x in right if x == x], dtype=float)
    if a.size < 2 or b.size < 2:
        return 0.0
    denom = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    if denom == 0.0 or denom != denom:
        return 0.0
    return float((a.mean() - b.mean()) / denom)


def summarize(values: Sequence[float], *, label: str) -> WindowStats:
    """Mean/median/std/%pos/one-sample-t for a daily-return population. Pure."""

    vals = [float(v) for v in values if v == v]
    n = len(vals)
    if n == 0:
        return WindowStats(label, 0, float("nan"), float("nan"), float("nan"), float("nan"), 0.0)
    s = pd.Series(vals)
    return WindowStats(
        label=label,
        n=n,
        mean=float(s.mean()),
        median=float(s.median()),
        std=float(s.std(ddof=1)) if n > 1 else 0.0,
        pct_positive=float((s > 0).mean()),
        t_stat=_one_sample_t(vals),
    )


def turn_of_month_mask(
    index: pd.DatetimeIndex,
    *,
    tom_days: Sequence[int] = TOM_TRADING_DAYS,
) -> pd.Series:
    """Boolean mask over ``index`` marking turn-of-month trading days.

    A day is TOM iff its **within-month trading-day rank** (1 = first trading day
    of its calendar month) is in the "early" part of ``tom_days`` (the positive
    offsets), OR it is the **last** trading day of its calendar month (the ``-1``
    offset). Purely calendar-based — no returns are consulted. Pure.

    ``index`` need not be contiguous; rank is computed within each (year, month).
    """

    idx = pd.DatetimeIndex(index).sort_values()
    df = pd.DataFrame(index=idx)
    ym = idx.to_period("M")
    # rank of each trading day within its calendar month (1-based).
    rank_in_month = pd.Series(idx, index=idx).groupby(ym).cumcount() + 1
    count_in_month = pd.Series(1, index=idx).groupby(ym).transform("size")

    early_offsets = sorted(d for d in tom_days if d > 0)
    include_ldom = -1 in tom_days

    early = rank_in_month.isin(early_offsets)
    last = (rank_in_month == count_in_month) if include_ldom else pd.Series(False, index=idx)
    mask = early | last
    mask.name = "tom"
    df["tom"] = mask
    return df["tom"]


def compute_tom(
    returns: pd.Series,
    *,
    cost: float = PER_DAY_COST,
    tom_days: Sequence[int] = TOM_TRADING_DAYS,
) -> TomResult:
    """Split a daily-return series into TOM and ROM populations and compare. Pure.

    ``returns`` is a date-indexed series of close-to-close simple returns (the
    first day's NaN return, if present, is dropped by cleaning).
    """

    r = _clean_returns(returns)
    mask = turn_of_month_mask(r.index, tom_days=tom_days).reindex(r.index).fillna(False)
    tom_vals = r[mask.to_numpy()].tolist()
    rom_vals = r[~mask.to_numpy()].tolist()
    tom = summarize(tom_vals, label="tom")
    rom = summarize(rom_vals, label="rom")
    diff = tom.mean - rom.mean if tom.n and rom.n else float("nan")
    return TomResult(
        tom=tom,
        rom=rom,
        diff=diff,
        after_cost_diff=diff - cost if diff == diff else float("nan"),
        welch_t=_welch_t(tom_vals, rom_vals),
    )


def placebo_diffs(
    returns: pd.Series,
    *,
    n_trials: int,
    seed: int = 0,
    tom_days: Sequence[int] = TOM_TRADING_DAYS,
) -> list[float]:
    """Distribution of TOM-vs-ROM Welch t under RANDOM pseudo-month-turns.

    Each trial picks, for every calendar month, a random in-month anchor day and
    labels {anchor, anchor+1, anchor+2, anchor+3} (the same 4-day shape) as the
    pseudo-window, then computes the pseudo-TOM minus pseudo-ROM Welch t. Real
    TOM structure should make the true |t| exceed this null band. Pure (seeded).
    """

    r = _clean_returns(returns)
    idx = r.index
    ym = idx.to_period("M")
    width = len([d for d in tom_days if d > 0]) + (1 if -1 in tom_days else 0)
    rng = np.random.default_rng(seed)
    positions = np.arange(len(idx))
    out: list[float] = []
    for _ in range(n_trials):
        pseudo = np.zeros(len(idx), dtype=bool)
        for _period, grp in pd.Series(positions, index=ym).groupby(level=0):
            pos = grp.to_numpy()
            if pos.size == 0:
                continue
            start_local = int(rng.integers(0, pos.size))
            chosen = pos[start_local : start_local + width]
            pseudo[chosen] = True
        vals = r.to_numpy()
        out.append(_welch_t(vals[pseudo].tolist(), vals[~pseudo].tolist()))
    return out


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    full: TomResult,
    is_res: TomResult,
    oos_res: TomResult,
    placebo_abs_t_95: float,
    *,
    min_half_n: int = 100,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T48 gate (ALL must hold):

    IS and OOS TOM N >= min_half_n; AFTER-COST full-sample TOM-ROM difference
    positive with Welch |t| >= t_threshold; IS/OOS TOM-ROM diffs same sign; the
    real full-sample |welch_t| exceeds the placebo 95th-pct |t| band. Each line
    is reported PASS/FAIL.
    """

    reasons: list[str] = []

    enough = is_res.tom.n >= min_half_n and oos_res.tom.n >= min_half_n
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: TOM N — IS={is_res.tom.n} OOS={oos_res.tom.n} "
        f"(need both >= {min_half_n})"
    )

    sig = (full.after_cost_diff > 0) and (abs(full.welch_t) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: after-cost signal — TOM-ROM net diff="
        f"{full.after_cost_diff:+.6f} Welch t={full.welch_t:+.2f} "
        f"(need >0 & |t|>={t_threshold})"
    )

    same_sign = (is_res.diff > 0 and oos_res.diff > 0) or (
        is_res.diff < 0 and oos_res.diff < 0
    )
    reasons.append(
        f"{'PASS' if same_sign else 'FAIL'}: OOS sign stable — IS diff={is_res.diff:+.6f} "
        f"OOS diff={oos_res.diff:+.6f} (need same sign)"
    )

    placebo_ok = abs(full.welch_t) > abs(placebo_abs_t_95)
    reasons.append(
        f"{'PASS' if placebo_ok else 'FAIL'}: placebo — real |t|={abs(full.welch_t):.2f} "
        f"vs placebo 95th-pct |t|={abs(placebo_abs_t_95):.2f} (need real > placebo)"
    )

    return GateVerdict(
        passed=enough and sig and same_sign and placebo_ok, reasons=reasons
    )
