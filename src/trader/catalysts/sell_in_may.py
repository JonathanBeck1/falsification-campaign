"""Campaign test T49 — the "Sell-in-May" / Halloween indicator.

Pre-registered in ``research/sell_in_may_preregistration.md``. Falsify-first.

Hypothesis: SPY's *winter* half (Nov-Apr) out-returns its *summer* half
(May-Oct), and a seasonal allocation that holds SPY Nov-Apr and sits in cash
May-Oct beats buy-and-hold **on a risk-adjusted (Sharpe) basis after costs**.

Honest prior (see pre-reg §2): the seasonal split itself is somewhat real and
heavily publicized, so we expect winter mean > summer mean but expect the
*strategy* to win (if at all) only by holding ~half the market exposure — i.e.
lower volatility / lower drawdown, **not** alpha. The decisive question is
whether seasonal Sharpe exceeds buy-and-hold Sharpe; if not, the "edge" is just
reduced exposure (a beta artifact, brain/30 artifact-class "decayed / exposure").

The "season" of every month is fixed by the **calendar month number alone**
(11,12,1-4 -> winter/in-market; 5-10 -> summer/cash). This is fully ex-ante:
the allocation for a month uses no price or return realized in or after it. There
is no look-ahead — the only information used is the date.

Everything in this module is **pure**: it operates on an in-memory monthly-return
series and does no I/O. Only the runner script touches yfinance. Unit-tested on
synthetic series with an injected seasonal effect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

# Welch two-sample t lives in the shared gate (ddof=1; 0.0 on <2 obs or zero
# pooled SE). Behaviorally identical to the former local helper here: every call
# site feeds it ``split_by_season`` output, which has already applied the same
# ``MAX_ABS_MONTHLY_RET`` glitch clip, so the gate version's NaN/inf-only drop
# yields the same result. Re-exported under the original name so callers and
# tests that import ``welch_t`` from this module are unchanged.
from trader.research.gate import welch_t as welch_t

# Calendar months held in equities ("winter"); the rest are held in cash.
WINTER_MONTHS: frozenset[int] = frozenset({11, 12, 1, 2, 3, 4})
SUMMER_MONTHS: frozenset[int] = frozenset({5, 6, 7, 8, 9, 10})

# SPY round-trip cost: ~2 bps (1 bp each way). The seasonal strategy does ONE
# round trip per year (exit Apr-close -> cash, re-enter Oct-close). So annual
# friction is ~2 bps -- negligible; see pre-reg sec.6.
ROUND_TRIP_COST = 0.0002
MONTHS_PER_YEAR = 12

# A single monthly SPY return beyond this magnitude is a data glitch, not a real
# move; it is dropped (counted, never hidden).
MAX_ABS_MONTHLY_RET = 0.60


# --------------------------------------------------------------------------- #
# small pure stats
# --------------------------------------------------------------------------- #
def is_winter(month: int) -> bool:
    """True if the calendar ``month`` (1-12) is an in-market (Nov-Apr) month."""

    return month in WINTER_MONTHS


def _clean(values: list[float]) -> list[float]:
    return [float(v) for v in values if v == v and abs(float(v)) <= MAX_ABS_MONTHLY_RET]


def mean(values: list[float]) -> float:
    vals = _clean(values)
    return float(sum(vals) / len(vals)) if vals else float("nan")


def std(values: list[float], *, ddof: int = 1) -> float:
    vals = _clean(values)
    n = len(vals)
    if n - ddof <= 0:
        return float("nan")
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / (n - ddof)
    return math.sqrt(var)


def annualized_sharpe(monthly_returns: list[float], *, rf_monthly: float = 0.0) -> float:
    """Annualized Sharpe of a monthly excess-return series.

    Sharpe = mean(excess) / std(excess) * sqrt(12). ``rf_monthly`` is the
    per-month risk-free rate subtracted before the ratio (0.0 = excess over cash,
    the conservative pre-registered choice). NaN if < 2 obs or zero variance.
    """

    vals = _clean(monthly_returns)
    if len(vals) < 2:
        return float("nan")
    excess = [v - rf_monthly for v in vals]
    sd = std(excess)
    if sd != sd or sd == 0.0:
        return float("nan")
    return (sum(excess) / len(excess)) / sd * math.sqrt(MONTHS_PER_YEAR)


def annualized_return(monthly_returns: list[float]) -> float:
    """Geometric annualized return from a monthly simple-return series."""

    vals = _clean(monthly_returns)
    if not vals:
        return float("nan")
    growth = 1.0
    for v in vals:
        growth *= 1.0 + v
    return growth ** (MONTHS_PER_YEAR / len(vals)) - 1.0


# --------------------------------------------------------------------------- #
# monthly returns + season split
# --------------------------------------------------------------------------- #
def to_monthly_returns(close: pd.Series) -> pd.Series:
    """Convert a daily adjusted-close series to month-end simple returns.

    Index is the month-end timestamp; value is that month's close-to-close
    return. Pure (no I/O). Drops the first (NaN) month.
    """

    s = close.dropna().sort_index()
    s.index = pd.DatetimeIndex(s.index)
    monthly_close = s.resample("ME").last().dropna()
    rets = monthly_close.pct_change().dropna()
    rets.name = "monthly_return"
    return rets


@dataclass(frozen=True)
class SeasonSplit:
    """Winter (in-market) vs summer (cash) monthly returns, by calendar month."""

    winter: list[float]
    summer: list[float]

    @property
    def n_winter(self) -> int:
        return len(self.winter)

    @property
    def n_summer(self) -> int:
        return len(self.summer)


def split_by_season(monthly_returns: pd.Series) -> SeasonSplit:
    """Partition a monthly-return series into winter (Nov-Apr) and summer
    (May-Oct) buckets by the timestamp's calendar month. Pure.
    """

    winter: list[float] = []
    summer: list[float] = []
    for ts, r in monthly_returns.items():
        rv = float(r)
        if abs(rv) > MAX_ABS_MONTHLY_RET or rv != rv:
            continue
        (winter if is_winter(pd.Timestamp(ts).month) else summer).append(rv)
    return SeasonSplit(winter=winter, summer=summer)


# --------------------------------------------------------------------------- #
# seasonal strategy vs buy-and-hold
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StrategyStats:
    """Performance of one monthly-return stream."""

    label: str
    n: int
    ann_return: float
    ann_vol: float
    sharpe: float
    time_in_market: float  # fraction of months actually holding equities


def seasonal_strategy_returns(
    monthly_returns: pd.Series,
    *,
    rf_monthly: float = 0.0,
    round_trip_cost: float = ROUND_TRIP_COST,
) -> list[float]:
    """Monthly returns of the seasonal allocation.

    Winter months earn the SPY monthly return; summer months earn ``rf_monthly``
    (cash). The round-trip cost is charged ONCE PER YEAR, on the winter-entry
    month (November) -- that single annual switch (cash->SPY) plus its later
    Apr->cash exit is one round trip. Pure.
    """

    out: list[float] = []
    for ts, r in monthly_returns.items():
        month = pd.Timestamp(ts).month
        rv = float(r)
        if month in WINTER_MONTHS:
            ret = rv if (abs(rv) <= MAX_ABS_MONTHLY_RET and rv == rv) else 0.0
            if month == 11:  # the annual re-entry month bears the round trip
                ret -= round_trip_cost
            out.append(ret)
        else:
            out.append(rf_monthly)
    return out


def buy_and_hold_returns(monthly_returns: pd.Series) -> list[float]:
    """Monthly returns of buy-and-hold SPY (the benchmark). Pure."""

    return [
        float(r)
        for r in monthly_returns.to_list()
        if float(r) == float(r) and abs(float(r)) <= MAX_ABS_MONTHLY_RET
    ]


def summarize_strategy(
    monthly_returns: list[float],
    *,
    label: str,
    rf_monthly: float = 0.0,
    time_in_market: float = 1.0,
) -> StrategyStats:
    """Annualized return / vol / Sharpe / time-in-market for a return stream."""

    n = len(_clean(monthly_returns))
    ann_vol = std(monthly_returns) * math.sqrt(MONTHS_PER_YEAR)
    return StrategyStats(
        label=label,
        n=n,
        ann_return=annualized_return(monthly_returns),
        ann_vol=ann_vol,
        sharpe=annualized_sharpe(monthly_returns, rf_monthly=rf_monthly),
        time_in_market=time_in_market,
    )


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    split_full: SeasonSplit,
    seasonal_full: StrategyStats,
    bh_full: StrategyStats,
    diff_t_full: float,
    split_is: SeasonSplit,
    split_oos: SeasonSplit,
    seasonal_sharpe_is: float,
    bh_sharpe_is: float,
    seasonal_sharpe_oos: float,
    bh_sharpe_oos: float,
    *,
    min_n: int = 30,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T49 gate (ALL must hold), from brain/30.

    1. N >= ``min_n`` monthly obs in EACH season.
    2. Winter > summer with seasonal-difference |t| >= ``t_threshold``.
    3. THE decisive gate: after-cost seasonal Sharpe > buy-and-hold Sharpe.
    4. OOS sign stability: winter-summer diff same sign IS vs OOS (both N>=10),
       AND the seasonal>=B&H-Sharpe verdict does not flip across halves.
    Each line is reported PASS/FAIL.
    """

    reasons: list[str] = []

    enough = split_full.n_winter >= min_n and split_full.n_summer >= min_n
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: N — winter={split_full.n_winter} "
        f"summer={split_full.n_summer} (need each >= {min_n})"
    )

    win_mean = mean(split_full.winter)
    sum_mean = mean(split_full.summer)
    seasonal_real = (win_mean > sum_mean) and (abs(diff_t_full) >= t_threshold)
    reasons.append(
        f"{'PASS' if seasonal_real else 'FAIL'}: seasonal split — winter mean="
        f"{win_mean:+.5f} vs summer mean={sum_mean:+.5f}, Welch t={diff_t_full:+.2f} "
        f"(need winter>summer & |t|>={t_threshold})"
    )

    sharpe_edge = seasonal_full.sharpe > bh_full.sharpe
    reasons.append(
        f"{'PASS' if sharpe_edge else 'FAIL'}: risk-adjusted edge (DECISIVE) — "
        f"seasonal Sharpe={seasonal_full.sharpe:+.3f} vs buy-and-hold Sharpe="
        f"{bh_full.sharpe:+.3f} (need seasonal > B&H; else it's exposure not alpha)"
    )

    is_n_ok = (
        split_is.n_winter >= 10
        and split_is.n_summer >= 10
        and split_oos.n_winter >= 10
        and split_oos.n_summer >= 10
    )
    diff_is = mean(split_is.winter) - mean(split_is.summer)
    diff_oos = mean(split_oos.winter) - mean(split_oos.summer)
    same_sign = (diff_is > 0 and diff_oos > 0) or (diff_is < 0 and diff_oos < 0)
    verdict_is = seasonal_sharpe_is > bh_sharpe_is
    verdict_oos = seasonal_sharpe_oos > bh_sharpe_oos
    verdict_stable = verdict_is == verdict_oos
    oos_ok = is_n_ok and same_sign and verdict_stable
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS stability — diff IS={diff_is:+.5f} "
        f"OOS={diff_oos:+.5f} (same sign); Sharpe-edge IS={verdict_is} OOS="
        f"{verdict_oos} (need same sign & stable verdict, all halves N>=10)"
    )

    return GateVerdict(
        passed=enough and seasonal_real and sharpe_edge and oos_ok,
        reasons=reasons,
    )
