"""Campaign test T26 — put-call-parity deviation / implied hard-to-borrow rate.

Pre-registered in ``research/putcall_parity_borrow_preregistration.md``.
Falsify-first. Reuses the audited vol-surface foundation
(:mod:`trader.catalysts.vol_surface_data`) for the lake loader and the
spot/quote cleaning; this module adds only the *pure* parity math, the
cross-sectional sort, and the pre-registered gate.

### The economics

European put-call parity with a continuous carry rate ``q`` (dividend yield +
any borrow drag) is::

    C - P = S * e^{-q*tau} - K * e^{-r*tau}

Solving for the chain-**implied carry**::

    q* = - ln( (C - P + K*e^{-r*tau}) / S ) / tau

For a name that pays no dividend, ``q*`` is the options-**implied borrow** plus
noise. A genuinely hard-to-borrow stock has a depressed implied forward, so its
implied borrow is high (Ofek-Richardson-Whitelaw 2004); such names are
over-valued and subsequently under-perform. The test sorts names cross-
sectionally on implied borrow and asks whether high-borrow names earn lower
after-cost forward returns.

### Honest prior (stated in the pre-reg)

Our universe is 24 easy-to-borrow mega-caps + 2 index ETFs. Implied borrow
should be ~0 with no cross-sectional dispersion to sort on. The pre-registered
most-likely outcome is a DATA_WALL: the right universe (hard-to-borrow small
caps) is not in the lake. This module makes that determination explicit via the
**dispersion precondition** in the gate.

### Purity

Every function here is a **pure** function of in-memory frames / arrays — no I/O,
no network. Only the runner script reads the lake (via the foundation loader)
and yfinance. Unit-tested on synthetic chains with a *known* injected borrow so
the solver's recovered ``q*`` can be checked against the exact answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from trader.catalysts.vol_surface_data import DEFAULT_RISK_FREE_RATE

# --------------------------------------------------------------------------- #
# Pre-registered constants (see research/putcall_parity_borrow_preregistration.md)
# --------------------------------------------------------------------------- #
# Near-the-money band for parity pairs: |K/S - 1| <= this. Parity is cleanest at
# the money where both legs carry real two-sided value (deep ITM/OTM legs have
# one near-zero price whose spread dominates the C-P difference).
DEFAULT_MONEYNESS_WINDOW = 0.05

# Clean tenor band in years: drop <7d (pin/expiry microstructure) and >120d
# (thin, stale quotes) — parity noise blows up at both ends.
DEFAULT_MIN_TAU = 7.0 / 365.0
DEFAULT_MAX_TAU = 120.0 / 365.0

# A single per-pair implied carry beyond this magnitude (in absolute annualized
# rate) is a bad/stale quote, not a real borrow, and is dropped (counted).
MAX_ABS_CARRY = 1.50  # 150% annualized

# Forward-return windows in trading days. PRIMARY = fwd_21d (matches the monthly
# rebalance); the others are reported but never replace it.
FORWARD_WINDOWS: dict[str, int] = {
    "fwd_21d": 21,  # PRIMARY
    "fwd_5d": 5,
    "fwd_63d": 63,
}
PRIMARY_WINDOW = "fwd_21d"

# Single-name equity round-trip ~10 bps; a long-short spread crosses two names
# (one long leg, one short leg) -> 20 bps per rebalance against the spread.
ROUND_TRIP_COST_PER_LEG = 0.0010
SPREAD_COST = 2 * ROUND_TRIP_COST_PER_LEG  # 20 bps

# Dispersion precondition: the per-date cross-sectional implied-borrow spread
# (top tercile minus bottom tercile, in annualized rate) must exceed this for
# there to be anything to sort on. Below it, the universe is effectively
# constant-borrow and the test is a DATA_WALL, not a tradeable null. 1% (100 bps)
# is a generous floor: real HTB fees run 1%-100%+/yr, easy-to-borrow GC is <0.5%.
MIN_BORROW_DISPERSION = 0.01  # 100 bps annualized

# Tercile fraction for the cross-sectional sort.
TERCILE = 1.0 / 3.0


# --------------------------------------------------------------------------- #
# small pure stats (mirrors earnings_premium.py for consistency)
# --------------------------------------------------------------------------- #
def _clean(values: list[float]) -> list[float]:
    return [float(v) for v in values if v == v]


def mean(values: list[float]) -> float:
    vals = _clean(values)
    return float(sum(vals) / len(vals)) if vals else float("nan")


def median(values: list[float]) -> float:
    vals = sorted(_clean(values))
    n = len(vals)
    if n == 0:
        return float("nan")
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def std(values: list[float], *, ddof: int = 1) -> float:
    vals = _clean(values)
    n = len(vals)
    if n - ddof <= 0:
        return float("nan")
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / (n - ddof)
    return math.sqrt(var)


def t_stat_one_sample(values: list[float]) -> float:
    """One-sample t-statistic against 0 (mean / SE). 0.0 if < 2 usable obs."""

    vals = _clean(values)
    n = len(vals)
    if n < 2:
        return 0.0
    sd = std(vals)
    if sd != sd or sd == 0.0:
        return 0.0
    return (sum(vals) / n) / (sd / math.sqrt(n))


def iqr(values: list[float]) -> float:
    """Inter-quartile range (Q3 - Q1); NaN-robust noise-floor estimator."""

    vals = sorted(_clean(values))
    if len(vals) < 4:
        return float("nan")
    q1 = float(np.percentile(vals, 25))
    q3 = float(np.percentile(vals, 75))
    return q3 - q1


# --------------------------------------------------------------------------- #
# PURE parity math
# --------------------------------------------------------------------------- #
def implied_carry(
    call_mid: np.ndarray,
    put_mid: np.ndarray,
    spot: np.ndarray,
    strike: np.ndarray,
    tau: np.ndarray,
    *,
    r: float = DEFAULT_RISK_FREE_RATE,
) -> np.ndarray:
    """Options-implied continuous carry rate ``q*`` from put-call parity.

    Solves ``C - P = S*e^{-q* tau} - K*e^{-r tau}`` for ``q*`` per matched
    (call, put) pair::

        q* = - ln( (C - P + K*e^{-r tau}) / S ) / tau

    For a zero-dividend name this is the implied **borrow** rate (+ noise): a
    depressed implied forward (hard-to-borrow) gives a higher ``q*``. Returns
    NaN where the parity argument is non-positive (no real solution), or any
    input is non-finite/non-positive. Inputs broadcast; arrays in/out. PURE.
    """

    C = np.asarray(call_mid, dtype=float)
    P = np.asarray(put_mid, dtype=float)
    S = np.asarray(spot, dtype=float)
    K = np.asarray(strike, dtype=float)
    T = np.asarray(tau, dtype=float)

    valid = (
        np.isfinite(C)
        & np.isfinite(P)
        & np.isfinite(S)
        & np.isfinite(K)
        & np.isfinite(T)
        & (S > 0)
        & (K > 0)
        & (T > 0)
    )
    disc_k = np.where(valid, K * np.exp(-r * T), np.nan)
    arg = np.where(valid, (C - P + disc_k) / S, np.nan)
    arg = np.where(arg > 0, arg, np.nan)  # ln of non-positive has no real carry
    with np.errstate(invalid="ignore", divide="ignore"):
        q = -np.log(arg) / T
    return np.where(np.isfinite(q), q, np.nan)


@dataclass(frozen=True)
class NameDateBorrow:
    """Per-(name, trade_date) robust implied borrow from near-the-money pairs."""

    ticker: str
    trade_date: pd.Timestamp
    spot: float
    n_pairs: int  # qualifying matched pairs that produced a finite carry
    implied_borrow: float  # robust (median) q* across qualifying pairs


def parity_pairs(
    quotes: pd.DataFrame,
    *,
    moneyness_window: float = DEFAULT_MONEYNESS_WINDOW,
    min_tau: float = DEFAULT_MIN_TAU,
    max_tau: float = DEFAULT_MAX_TAU,
    r: float = DEFAULT_RISK_FREE_RATE,
    max_abs_carry: float = MAX_ABS_CARRY,
) -> pd.DataFrame:
    """Matched (expiration, strike) call/put pairs with their implied carry.

    ``quotes`` is the output of
    :func:`trader.catalysts.vol_surface_data.load_option_quotes` for ONE
    (ticker, trade_date): columns ``expiration, strike, right, mid, tau,
    underlying``. Returns one row per qualifying matched pair with columns
    ``expiration, strike, tau, moneyness, call_mid, put_mid, q_star``. A pair
    qualifies if both legs are present, |K/S - 1| <= ``moneyness_window``,
    ``min_tau <= tau <= max_tau``, and |q_star| <= ``max_abs_carry``. PURE.
    """

    cols = ["expiration", "strike", "tau", "moneyness", "call_mid", "put_mid", "q_star"]
    if quotes.empty:
        return pd.DataFrame(columns=cols)

    q = quotes.copy()
    spot = float(q["underlying"].iloc[0])
    q = q[(q["tau"] >= min_tau) & (q["tau"] <= max_tau)]
    if q.empty:
        return pd.DataFrame(columns=cols)
    q = q[(np.abs(q["strike"] / spot - 1.0) <= moneyness_window)]
    if q.empty:
        return pd.DataFrame(columns=cols)

    calls = q[q["right"] == "C"][["expiration", "strike", "tau", "mid"]].rename(
        columns={"mid": "call_mid"}
    )
    puts = q[q["right"] == "P"][["expiration", "strike", "mid"]].rename(
        columns={"mid": "put_mid"}
    )
    pairs = calls.merge(puts, on=["expiration", "strike"], how="inner")
    if pairs.empty:
        return pd.DataFrame(columns=cols)

    pairs = pairs.assign(
        moneyness=pairs["strike"] / spot,
        q_star=implied_carry(
            pairs["call_mid"].to_numpy(),
            pairs["put_mid"].to_numpy(),
            np.full(len(pairs), spot),
            pairs["strike"].to_numpy(),
            pairs["tau"].to_numpy(),
            r=r,
        ),
    )
    pairs = pairs[np.isfinite(pairs["q_star"]) & (np.abs(pairs["q_star"]) <= max_abs_carry)]
    return pairs[cols].reset_index(drop=True)


def name_date_borrow(
    quotes: pd.DataFrame,
    ticker: str,
    trade_date: pd.Timestamp | str,
    *,
    moneyness_window: float = DEFAULT_MONEYNESS_WINDOW,
    min_tau: float = DEFAULT_MIN_TAU,
    max_tau: float = DEFAULT_MAX_TAU,
    r: float = DEFAULT_RISK_FREE_RATE,
    min_pairs: int = 2,
) -> NameDateBorrow | None:
    """Robust per-(name, date) implied borrow = median q* over qualifying pairs.

    Returns ``None`` if fewer than ``min_pairs`` qualifying pairs exist (we
    require a small floor so one stale pair cannot define the borrow). Uses the
    **median** of per-pair ``q_star`` (brain/30 class-3 defense: a single bad
    quote must not move the per-name number). PURE.
    """

    pairs = parity_pairs(
        quotes,
        moneyness_window=moneyness_window,
        min_tau=min_tau,
        max_tau=max_tau,
        r=r,
    )
    if len(pairs) < min_pairs:
        return None
    return NameDateBorrow(
        ticker=ticker,
        trade_date=pd.Timestamp(trade_date),
        spot=float(quotes["underlying"].iloc[0]),
        n_pairs=len(pairs),
        implied_borrow=float(np.median(pairs["q_star"].to_numpy())),
    )


# --------------------------------------------------------------------------- #
# Cross-sectional sort + forward returns
# --------------------------------------------------------------------------- #
def forward_return(close: pd.Series, t0_date: pd.Timestamp, horizon: int) -> float:
    """Simple forward return over (t0, t0+horizon] trading days from a close series.

    ``close`` is a date-indexed close series (one ticker). ``t0_date`` is the
    rebalance date; the entry is the close at the first session on/after t0 and
    the exit is ``horizon`` sessions later. Returns NaN if either endpoint is
    missing. PURE.
    """

    s = close.dropna().sort_index()
    idx = pd.DatetimeIndex(s.index)
    pos = int(idx.searchsorted(pd.Timestamp(t0_date), side="left"))
    if pos >= len(s) or pos + horizon >= len(s):
        return float("nan")
    p0 = float(s.iloc[pos])
    p1 = float(s.iloc[pos + horizon])
    if p0 <= 0 or p1 <= 0:
        return float("nan")
    return p1 / p0 - 1.0


@dataclass(frozen=True)
class RebalanceSpread:
    """One rebalance date's high-minus-low-borrow cross-section.

    ``spread`` is the pre-registered LOW-borrow minus HIGH-borrow forward
    return (the predicted-positive signal: high-borrow under-performs). The
    cross-section is SPY-adjusted, so ``spread`` already nets the market move.
    """

    trade_date: pd.Timestamp
    n_names: int
    borrow_dispersion: float  # top-tercile mean borrow - bottom-tercile mean borrow
    high_borrow_ret: float  # mean fwd abnormal return of the top-tercile (high borrow)
    low_borrow_ret: float  # mean fwd abnormal return of the bottom-tercile (low borrow)
    spread: float  # low - high (predicted > 0)


def cross_section_spread(
    borrows: list[tuple[str, float]],
    abn_returns: dict[str, float],
    trade_date: pd.Timestamp,
    *,
    tercile: float = TERCILE,
) -> RebalanceSpread | None:
    """Build one rebalance's low-minus-high implied-borrow return spread. PURE.

    ``borrows`` is ``[(ticker, implied_borrow), ...]`` for the names with a valid
    borrow on this date; ``abn_returns`` maps ticker -> forward abnormal return.
    Names are sorted by borrow; the top ``tercile`` (high borrow) and bottom
    ``tercile`` (low borrow) form the two legs. Returns ``None`` if fewer than 3
    names (can't form terciles) or a leg ends up empty.
    """

    usable = [
        (t, b, abn_returns[t])
        for t, b in borrows
        if t in abn_returns and b == b and abn_returns[t] == abn_returns[t]
    ]
    n = len(usable)
    if n < 3:
        return None
    usable.sort(key=lambda x: x[1])  # ascending borrow
    k = max(1, round(n * tercile))
    low = usable[:k]  # lowest borrow
    high = usable[-k:]  # highest borrow
    if not low or not high:
        return None

    low_ret = mean([r for _, _, r in low])
    high_ret = mean([r for _, _, r in high])
    dispersion = mean([b for _, b, _ in high]) - mean([b for _, b, _ in low])
    return RebalanceSpread(
        trade_date=pd.Timestamp(trade_date),
        n_names=n,
        borrow_dispersion=dispersion,
        high_borrow_ret=high_ret,
        low_borrow_ret=low_ret,
        spread=low_ret - high_ret,
    )


# --------------------------------------------------------------------------- #
# Aggregation + gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SpreadStats:
    """Pooled after-cost stats for a list of rebalance spreads."""

    label: str
    n: int
    gross_mean: float
    after_cost_mean: float
    median: float
    t_stat: float  # t of the after-cost spreads vs 0
    win_rate: float
    sharpe: float


def aggregate_spreads(
    spreads: list[float],
    *,
    label: str,
    spread_cost: float = SPREAD_COST,
) -> SpreadStats:
    """Pool rebalance spreads into after-cost stats. PURE."""

    vals = _clean(spreads)
    n = len(vals)
    gross = mean(vals)
    after = [v - spread_cost for v in vals]
    sd = std(vals)
    sharpe = (gross / sd) if (sd == sd and sd > 0) else float("nan")
    win = (sum(1 for v in vals if v > 0) / n) if n else float("nan")
    return SpreadStats(
        label=label,
        n=n,
        gross_mean=gross,
        after_cost_mean=mean(after),
        median=median(vals),
        t_stat=t_stat_one_sample(after),
        win_rate=win,
        sharpe=sharpe,
    )


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    data_wall: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_gate(
    *,
    n_spreads: int,
    after_cost_mean: float,
    after_cost_t: float,
    is_mean: float,
    is_n: int,
    oos_mean: float,
    oos_n: int,
    median_borrow_dispersion: float,
    placebo_t: float,
    min_n: int = 30,
    t_threshold: float = 2.0,
    min_dispersion: float = MIN_BORROW_DISPERSION,
) -> GateVerdict:
    """Pre-registered T26 gate (ALL must hold), from brain/30.

    The **dispersion precondition** is evaluated first and specially: if the
    cross-sectional implied borrow does not disperse beyond the noise floor,
    the universe is effectively constant-borrow and the result is a DATA_WALL
    (the effect cannot be tested on easy-to-borrow mega-caps) — NOT a tradeable
    null. Otherwise the standard gate applies:

    1. N >= ``min_n`` rebalance spreads.
    2. After-cost spread predicted-positive AND |t| >= ``t_threshold``.
    3. OOS sign stability: IS and OOS spread same sign, both N >= 10.
    4. Placebo (shuffled-borrow) spread ~0: |t| < ``t_threshold``.
    Each line is reported PASS/FAIL.
    """

    reasons: list[str] = []

    disperses = (
        median_borrow_dispersion == median_borrow_dispersion
        and median_borrow_dispersion >= min_dispersion
    )
    reasons.append(
        f"{'PASS' if disperses else 'DATA_WALL'}: cross-sectional borrow dispersion="
        f"{median_borrow_dispersion * 1e4:+.1f} bps/yr "
        f"(need >= {min_dispersion * 1e4:.0f} bps to have anything to sort on)"
    )

    enough = n_spreads >= min_n
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={n_spreads} (need >= {min_n})")

    primary_ok = after_cost_mean > 0 and abs(after_cost_t) >= t_threshold
    reasons.append(
        f"{'PASS' if primary_ok else 'FAIL'}: after-cost low-minus-high spread="
        f"{after_cost_mean * 100:+.4f}% t={after_cost_t:+.2f} "
        f"(need > 0 and |t| >= {t_threshold})"
    )

    halves_n_ok = is_n >= 10 and oos_n >= 10
    same_sign = (is_mean > 0 and oos_mean > 0) or (is_mean < 0 and oos_mean < 0)
    oos_ok = halves_n_ok and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stability IS={is_mean * 100:+.4f}% "
        f"(n={is_n}) OOS={oos_mean * 100:+.4f}% (n={oos_n}) "
        f"(need same sign, both n >= 10)"
    )

    placebo_null = abs(placebo_t) < t_threshold
    reasons.append(
        f"{'PASS' if placebo_null else 'FAIL'}: placebo (shuffled-borrow) "
        f"t={placebo_t:+.2f} (need |t| < {t_threshold})"
    )

    # If the universe doesn't disperse, the verdict is a DATA_WALL regardless of
    # the downstream lines (there was nothing to sort on).
    passed = disperses and enough and primary_ok and oos_ok and placebo_null
    return GateVerdict(passed=passed, data_wall=not disperses, reasons=reasons)
