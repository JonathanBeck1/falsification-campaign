"""Campaign test T43 — the earnings-announcement premium.

Pre-registered in ``research/earnings_premium_preregistration.md``. Falsify-first.

Hypothesis: holding a stock THROUGH its **scheduled** earnings announcement earns
a positive average **market-adjusted abnormal return** over a tight window
([-1,+1] in event-trading-day time) — compensation for bearing the scheduled
jump risk. This is the *announcement premium* (Beaver/Frazzini-Lamont/Barber et
al), DISTINCT from PEAD (post-earnings drift, killed in T07): the window
straddles the print rather than following it.

Discipline (brain/30 gate): the premium is measured as the announcement-window
abnormal return *minus the same stock's non-earnings-day baseline*, so any
single-name drift the market adjustment misses is differenced out. The
non-earnings windows double as the placebo (they must average ~0). The decisive
interpretation check is whether any positive mean is just **compensated
jump-risk variance** (premium scales with event-window volatility) rather than
alpha.

Everything in this module is **pure**: it operates on in-memory adjusted-close
series and does no I/O. Only the runner script touches yfinance. Unit-tested on
synthetic series with an injected announcement effect.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from trader.research.event_study import abnormal_returns as _shared_abnormal_returns
from trader.research.gate import t_stat as t_stat_one_sample
from trader.research.gate import welch_t

# Event-time CAR windows, in trading days relative to t0 (inclusive ranges).
# PRIMARY is car_m1_p1; the others are reported but never replace it.
EVENT_WINDOWS: dict[str, tuple[int, int]] = {
    "car_m1_p1": (-1, 1),  # PRIMARY: hold THROUGH the print
    "car_0_p1": (0, 1),  # strict no-pre-event-leg variant
    "car_0_p0": (0, 0),  # announcement day only
}
PRIMARY_WINDOW = "car_m1_p1"

# Trading-day padding we need around t0 to cover every window.
_NEED_LO = min(lo for lo, _ in EVENT_WINDOWS.values())
_NEED_HI = max(hi for _, hi in EVENT_WINDOWS.values())

# Days around each earnings event that are excluded from the non-earnings
# baseline (so placebo windows never overlap a real announcement reaction).
EARNINGS_EXCLUSION = 5

# A single daily abnormal return beyond this magnitude is treated as a data
# glitch and the event/window carrying it is dropped (counted, never hidden).
MAX_ABS_DAILY_ABN = 0.60

# Single-name large-cap round-trip cost: ~10 bps (5 bps each way). One round
# trip per event. Pre-registered in sec.6.
ROUND_TRIP_COST = 0.0010

# Hour-of-day (US/Eastern) at/after which an announcement is treated as
# after-market-close (AMC -> market prices it the NEXT session). Before this it
# is before-open (BMO -> same session). Missing time defaults to AMC.
AMC_HOUR_ET = 13


# --------------------------------------------------------------------------- #
# small pure stats
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


# The one-sample t (0.0-degenerate list form) and Welch two-sample t are the
# campaign's shared statistics, imported above as ``t_stat_one_sample`` (==
# :func:`trader.research.gate.t_stat`) and :func:`trader.research.gate.welch_t`.
# Both are behaviorally identical to the former local copies on this module's
# finite CARs (same ddof=1, same 0.0-on-degenerate / NaN-drop convention); the
# shared versions additionally drop ±inf, which ``compute_event`` /
# ``non_earnings_car`` already exclude via MAX_ABS_DAILY_ABN, so no value
# changes.


# --------------------------------------------------------------------------- #
# price / abnormal-return helpers
# --------------------------------------------------------------------------- #
def abnormal_returns(close: pd.Series, bench_close: pd.Series) -> pd.Series:
    """Daily market-adjusted abnormal returns: r_stock - r_bench (beta=1).

    Thin wrapper over :func:`trader.research.event_study.abnormal_returns` with
    the campaign's beta-1 (market-adjusted) convention. The benchmark is
    reindexed onto the stock's trading days and forward-filled. Pure. The first
    day is NaN (no prior close).
    """

    return _shared_abnormal_returns(close, bench_close, beta=1.0)


def is_amc(hour_et: int | None) -> bool:
    """True if an announcement at ``hour_et`` (US/Eastern, or None) is AMC.

    AMC means the market prices it the NEXT session. Missing time -> AMC
    (conservative: assume the reaction lands next session).
    """

    if hour_et is None:
        return True
    return int(hour_et) >= AMC_HOUR_ET


def resolve_t0_index(
    index: pd.DatetimeIndex,
    announcement_date: date,
    *,
    amc: bool,
) -> int | None:
    """Position in ``index`` of the first session that PRICES the release (t0).

    BMO: the first trading day on/after ``announcement_date``.
    AMC: the first trading day strictly AFTER ``announcement_date``.
    Returns ``None`` if no such session exists in range.
    """

    ts = pd.Timestamp(announcement_date)
    side = "right" if amc else "left"
    pos = int(index.searchsorted(ts, side=side))
    if pos >= len(index):
        return None
    return pos


@dataclass(frozen=True)
class EarningsEvent:
    """One earnings-announcement event's market-adjusted window CARs."""

    ticker: str
    announcement_date: date
    t0_date: date
    amc: bool
    cars: dict[str, float]  # window name -> cumulative abnormal return
    window_vol: float  # event-window realized vol (std of daily abn over [-1,+1])

    @property
    def primary(self) -> float:
        return self.cars[PRIMARY_WINDOW]


def compute_event(
    abn: pd.Series,
    announcement_date: date,
    ticker: str,
    *,
    amc: bool,
) -> EarningsEvent | None:
    """Compute one earnings event's window CARs from a daily abnormal-return series.

    ``abn`` is the output of :func:`abnormal_returns`. Returns ``None`` if the
    full [-1,+1] window (padded by the union of all windows) is not available or
    any in-window abnormal return is a glitch (> MAX_ABS_DAILY_ABN).
    """

    index = pd.DatetimeIndex(abn.index)
    t0 = resolve_t0_index(index, announcement_date, amc=amc)
    if t0 is None:
        return None
    lo = t0 + _NEED_LO
    hi = t0 + _NEED_HI
    if lo < 0 or hi >= len(abn):
        return None

    # Slice the needed event-day abnormal returns into an offset-keyed dict.
    by_offset: dict[int, float] = {}
    for offset in range(_NEED_LO, _NEED_HI + 1):
        val = abn.iloc[t0 + offset]
        if val != val or abs(float(val)) > MAX_ABS_DAILY_ABN:
            return None
        by_offset[offset] = float(val)

    cars: dict[str, float] = {}
    for name, (w_lo, w_hi) in EVENT_WINDOWS.items():
        cars[name] = sum(by_offset[o] for o in range(w_lo, w_hi + 1))

    p_lo, p_hi = EVENT_WINDOWS[PRIMARY_WINDOW]
    primary_legs = [by_offset[o] for o in range(p_lo, p_hi + 1)]
    window_vol = std(primary_legs)

    return EarningsEvent(
        ticker=ticker,
        announcement_date=announcement_date,
        t0_date=index[t0].date(),
        amc=amc,
        cars=cars,
        window_vol=window_vol if window_vol == window_vol else 0.0,
    )


def non_earnings_car(
    abn: pd.Series,
    t0_position: int,
    window: tuple[int, int],
) -> float | None:
    """3-day CAR at a placebo (non-earnings) anchor, same window shape as events.

    Returns ``None`` if the window runs off the series or carries a glitch.
    """

    w_lo, w_hi = window
    lo, hi = t0_position + w_lo, t0_position + w_hi
    if lo < 0 or hi >= len(abn):
        return None
    total = 0.0
    for offset in range(w_lo, w_hi + 1):
        val = abn.iloc[t0_position + offset]
        if val != val or abs(float(val)) > MAX_ABS_DAILY_ABN:
            return None
        total += float(val)
    return total


def sample_non_earnings_cars(
    abn: pd.Series,
    earnings_t0_positions: list[int],
    *,
    n_samples: int,
    window: tuple[int, int] = EVENT_WINDOWS[PRIMARY_WINDOW],
    rng: random.Random,
    exclusion: int = EARNINGS_EXCLUSION,
) -> list[float]:
    """Sample ``n_samples`` placebo CARs from non-earnings sessions of one ticker.

    A candidate anchor is valid if it is at least ``exclusion`` trading days from
    every earnings t0 and its window fits. Pure given ``rng``.
    """

    n = len(abn)
    if n == 0:
        return []
    blocked: set[int] = set()
    for pos in earnings_t0_positions:
        for d in range(pos - exclusion, pos + exclusion + 1):
            blocked.add(d)
    w_lo, w_hi = window
    candidates = [
        p for p in range(-w_lo, n - w_hi) if p not in blocked
    ]
    if not candidates:
        return []
    rng.shuffle(candidates)
    out: list[float] = []
    for pos in candidates:
        if len(out) >= n_samples:
            break
        car = non_earnings_car(abn, pos, window)
        if car is not None:
            out.append(car)
    return out


# --------------------------------------------------------------------------- #
# cohort aggregation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CohortStats:
    """Pooled stats for a set of event CARs on one window (after-cost optional)."""

    label: str
    n: int
    gross_mean: float
    after_cost_mean: float
    median: float
    t_stat: float  # t of the after-cost CARs against 0
    win_rate: float
    sharpe: float  # mean/std of the (gross) CARs — event-window Sharpe proxy


def aggregate(
    cars: list[float],
    *,
    label: str,
    round_trip_cost: float = ROUND_TRIP_COST,
) -> CohortStats:
    """Pool a list of window CARs into after-cost stats. Pure."""

    vals = _clean(cars)
    n = len(vals)
    gross = mean(vals)
    after = [v - round_trip_cost for v in vals]
    after_mean = mean(after)
    sd = std(vals)
    sharpe = (gross / sd) if (sd == sd and sd > 0) else float("nan")
    win = (sum(1 for v in vals if v > 0) / n) if n else float("nan")
    return CohortStats(
        label=label,
        n=n,
        gross_mean=gross,
        after_cost_mean=after_mean,
        median=median(vals),
        t_stat=t_stat_one_sample(after),
        win_rate=win,
        sharpe=sharpe,
    )


def premium_vs_baseline(
    event_cars: list[float],
    baseline_cars: list[float],
) -> tuple[float, float]:
    """(premium, Welch t) = event-window mean minus non-earnings-window mean.

    The premium nets out any same-stock drift the market adjustment missed.
    """

    premium = mean(event_cars) - mean(baseline_cars)
    return premium, welch_t(event_cars, baseline_cars)


def jump_risk_correlation(events: list[EarningsEvent]) -> float:
    """Pearson corr between event-window |CAR| and event-window vol.

    A high positive corr means the realized premium tracks jump-risk magnitude
    (compensated variance), supporting "risk premium, not alpha".
    """

    xs = [abs(e.primary) for e in events]
    ys = [e.window_vol for e in events]
    pairs = [(x, y) for x, y in zip(xs, ys, strict=True) if x == x and y == y]
    if len(pairs) < 2:
        return float("nan")
    xs2 = [p[0] for p in pairs]
    ys2 = [p[1] for p in pairs]
    mx, my = mean(xs2), mean(ys2)
    sx, sy = std(xs2), std(ys2)
    if sx == 0 or sy == 0 or sx != sx or sy != sy:
        return float("nan")
    cov = sum((x - mx) * (y - my) for x, y in pairs) / (len(pairs) - 1)
    return cov / (sx * sy)


# --------------------------------------------------------------------------- #
# pre-registered gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_gate(
    *,
    n_events: int,
    after_cost_mean: float,
    after_cost_t: float,
    is_mean: float,
    is_n: int,
    oos_mean: float,
    oos_n: int,
    placebo_mean: float,
    placebo_t: float,
    premium_vs_base: float,
    min_n: int = 30,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T43 gate (ALL must hold), from brain/30.

    1. N >= ``min_n`` usable events.
    2. After-cost announcement-window mean > 0 AND |t| >= ``t_threshold``.
    3. OOS sign stability: IS and OOS means same sign, both halves N >= 10.
    4. Placebo (non-earnings windows) ~0: |t| < ``t_threshold``.
    5. Premium survives baseline subtraction: premium_vs_base > 0.
    Each line is reported PASS/FAIL.
    """

    reasons: list[str] = []

    enough = n_events >= min_n
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: N={n_events} (need >= {min_n})"
    )

    primary_ok = after_cost_mean > 0 and abs(after_cost_t) >= t_threshold
    reasons.append(
        f"{'PASS' if primary_ok else 'FAIL'}: after-cost announcement mean="
        f"{after_cost_mean:+.5f} t={after_cost_t:+.2f} "
        f"(need > 0 and |t| >= {t_threshold})"
    )

    halves_n_ok = is_n >= 10 and oos_n >= 10
    same_sign = (is_mean > 0 and oos_mean > 0) or (is_mean < 0 and oos_mean < 0)
    oos_ok = halves_n_ok and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stability IS={is_mean:+.5f} "
        f"(n={is_n}) OOS={oos_mean:+.5f} (n={oos_n}) "
        f"(need same sign, both n >= 10)"
    )

    placebo_null = abs(placebo_t) < t_threshold
    reasons.append(
        f"{'PASS' if placebo_null else 'FAIL'}: placebo non-earnings mean="
        f"{placebo_mean:+.5f} t={placebo_t:+.2f} (need |t| < {t_threshold})"
    )

    survives = premium_vs_base > 0
    reasons.append(
        f"{'PASS' if survives else 'FAIL'}: premium vs same-stock baseline="
        f"{premium_vs_base:+.5f} (need > 0)"
    )

    return GateVerdict(
        passed=enough and primary_ok and oos_ok and placebo_null and survives,
        reasons=reasons,
    )
