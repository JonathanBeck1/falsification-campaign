"""Campaign test T41 — buyback-announcement drift.

Pre-registered in ``research/buyback_drift_preregistration.md``. Falsify-first.

Hypothesis: stocks filing an 8-K (Item 8.01) that announces a **new
share-repurchase authorization** earn a positive after-cost market-adjusted
cumulative abnormal return (CAR) over [+1,+21] (PRIMARY) and [+1,+63], in
excess of a matched (ticker, year) non-event control.

Mechanism (signaling / undervaluation, Ikenberry-Lakonishok-Vermaelen 1995):
management buys back when it thinks the stock is cheap and creates standing
demand; the market is said to under-react, producing a multi-month drift.
Honest prior: null-to-marginal — the long-run drift was a 1980s-90s value-stock
effect that has decayed, and the campaign's working hypothesis is that any raw
positive CAR is **mega-cap / universe drift (artifact class #5)** that dies to a
matched (ticker, year) control plus costs.

Everything in this module is **pure**: it operates on in-memory adjusted-close
series and pre-fetched event lists, doing no I/O. The runner script
(``scripts/run_buyback_drift_study.py``) owns all network access (EDGAR +
yfinance). Unit-tested on synthetic series with an injected drift.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# Shared event-study / gate plumbing, re-exported under the names the runner and
# tests import. ``abnormal_returns`` is the shared beta-1 market-adjusted version
# (its ``beta=1.0`` default makes ``1.0 * r_bench`` identical to the old
# ``- bench.pct_change()``); it internally uses the shared ``sorted_close``, which
# is byte-identical to the former local ``_sorted_close`` (drop NaN -> sort ->
# DatetimeIndex). ``t_stat``/``welch_t`` are behaviorally identical to the former
# local ``t_stat_one_sample``/``welch_t`` (same NaN-drop, ddof=1,
# 0.0-on-degenerate). The former private ``_sorted_close`` had no caller other
# than the old local ``abnormal_returns`` and is not re-exported.
from trader.research.event_study import abnormal_returns  # noqa: F401  (re-exported for runner/tests)
from trader.research.gate import t_stat as t_stat_one_sample
from trader.research.gate import welch_t

# Event-time CAR windows, in trading days relative to t0 (inclusive ranges).
# t0 itself is the first session strictly AFTER the 8-K file date; the first
# measured day is t0 (offset 0 == +1 relative to the file date in this
# convention is captured by the runner's t0 resolution). Here offsets are
# measured from t0, and every window starts at offset 0 so NO file-date return
# leaks in. PRIMARY is car_p1_p21; the others are reported, never replace it.
EVENT_WINDOWS: dict[str, tuple[int, int]] = {
    "car_p1_p21": (0, 20),  # PRIMARY: t0 .. t0+20 == [+1,+21] trading days
    "car_p1_p63": (0, 62),  # secondary: ~3 months (ILV horizon, scaled)
    "car_p1_p5": (0, 4),  # secondary: short-window reaction
}
PRIMARY_WINDOW = "car_p1_p21"

# Trading-day padding around t0 needed to cover every window.
_NEED_LO = min(lo for lo, _ in EVENT_WINDOWS.values())
_NEED_HI = max(hi for _, hi in EVENT_WINDOWS.values())

# Trading days around each event t0 excluded from the matched non-event
# baseline so placebo windows never overlap a real announcement reaction.
EVENT_EXCLUSION = 21

# A single daily abnormal return beyond this magnitude is treated as a data
# glitch; the event/window carrying it is dropped (counted, never hidden).
MAX_ABS_DAILY_ABN = 0.60

# Single-name small/mid-cap round-trip cost: ~15 bps (7.5 bps each way). One
# round trip per event. Pre-registered in sec.6.
ROUND_TRIP_COST = 0.0015


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


# One-sample t (``t_stat_one_sample``) and Welch two-sample t (``welch_t``) now
# come from :mod:`trader.research.gate` (imported above). They are behaviorally
# identical to the helpers that lived here: same ddof=1 sample std, same
# 0.0-on-degenerate (N<2 / zero-variance / zero pooled-SE) convention, same
# NaN-drop. The only difference is gate's ``_clean`` also drops ±inf, which is
# unreachable here: every CAR is a bounded finite sum (compute_event / window_car
# reject any |daily abn| > MAX_ABS_DAILY_ABN and any NaN), so no ±inf ever
# reaches these functions and no number moves.


# --------------------------------------------------------------------------- #
# event list construction (pure given raw EDGAR hits)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BuybackFiling:
    """One qualifying buyback-authorization 8-K (pre-price-join)."""

    ticker: str
    cik: str
    file_date: date
    accession: str


def quarter_key(d: date) -> tuple[int, int]:
    """(year, quarter) bucket for the (ticker, calendar-quarter) dedup."""

    return (d.year, (d.month - 1) // 3 + 1)


def dedup_filings(filings: list[BuybackFiling]) -> list[BuybackFiling]:
    """Keep the earliest filing per (ticker, calendar-quarter). Pure.

    Stops one multi-exhibit accession or a re-announced program from
    contributing several near-identical events and over-weighting serial
    repurchasers (pre-reg §4).
    """

    best: dict[tuple[str, tuple[int, int]], BuybackFiling] = {}
    for f in filings:
        key = (f.ticker, quarter_key(f.file_date))
        prev = best.get(key)
        if prev is None or f.file_date < prev.file_date:
            best[key] = f
    return sorted(best.values(), key=lambda f: (f.file_date, f.ticker))


# --------------------------------------------------------------------------- #
# price / abnormal-return helpers
# --------------------------------------------------------------------------- #
# ``abnormal_returns`` (beta-1 market-adjusted r_stock - r_bench, benchmark
# reindexed + ffilled onto the stock's days) now comes from
# :mod:`trader.research.event_study` (imported above). The shared
# ``abnormal_returns`` defaults ``beta=1.0``, and 1.0 * r_bench is numerically
# identical to the former local ``- bench.pct_change()`` — no number moves. It
# uses the shared ``sorted_close``, which is byte-identical to the former local
# ``_sorted_close``.


def resolve_t0_index(index: pd.DatetimeIndex, file_date: date) -> int | None:
    """Position in ``index`` of t0 = first session STRICTLY AFTER ``file_date``.

    8-K filings can post intraday/after close; next-session entry is the
    conservative, tradeable convention (pre-reg §4). Returns ``None`` if no
    such session exists in range.
    """

    ts = pd.Timestamp(file_date)
    pos = int(index.searchsorted(ts, side="right"))
    if pos >= len(index):
        return None
    return pos


@dataclass(frozen=True)
class BuybackEvent:
    """One buyback event's market-adjusted window CARs (post price-join)."""

    ticker: str
    file_date: date
    t0_date: date
    cars: dict[str, float]  # window name -> cumulative abnormal return

    @property
    def primary(self) -> float:
        return self.cars[PRIMARY_WINDOW]


def compute_event(
    abn: pd.Series,
    file_date: date,
    ticker: str,
) -> BuybackEvent | None:
    """Compute one event's window CARs from a daily abnormal-return series.

    ``abn`` is the output of :func:`abnormal_returns`. Returns ``None`` if the
    full padded window is not available or any in-window abnormal return is a
    glitch (> MAX_ABS_DAILY_ABN). The window starts at t0 (the session strictly
    after ``file_date``), so no file-date return leaks in.
    """

    index = pd.DatetimeIndex(abn.index)
    t0 = resolve_t0_index(index, file_date)
    if t0 is None:
        return None
    lo = t0 + _NEED_LO
    hi = t0 + _NEED_HI
    if lo < 0 or hi >= len(abn):
        return None

    by_offset: dict[int, float] = {}
    for offset in range(_NEED_LO, _NEED_HI + 1):
        val = abn.iloc[t0 + offset]
        if val != val or abs(float(val)) > MAX_ABS_DAILY_ABN:
            return None
        by_offset[offset] = float(val)

    cars: dict[str, float] = {}
    for name, (w_lo, w_hi) in EVENT_WINDOWS.items():
        cars[name] = sum(by_offset[o] for o in range(w_lo, w_hi + 1))

    return BuybackEvent(
        ticker=ticker,
        file_date=file_date,
        t0_date=index[t0].date(),
        cars=cars,
    )


def window_car(
    abn: pd.Series,
    anchor_position: int,
    window: tuple[int, int],
) -> float | None:
    """CAR at an arbitrary anchor for ``window`` (same shape as event windows).

    Returns ``None`` if the window runs off the series or carries a glitch.
    """

    w_lo, w_hi = window
    lo, hi = anchor_position + w_lo, anchor_position + w_hi
    if lo < 0 or hi >= len(abn):
        return None
    total = 0.0
    for offset in range(w_lo, w_hi + 1):
        val = abn.iloc[anchor_position + offset]
        if val != val or abs(float(val)) > MAX_ABS_DAILY_ABN:
            return None
        total += float(val)
    return total


def sample_matched_cars(
    abn: pd.Series,
    event_t0_positions: list[int],
    event_years: list[int],
    index: pd.DatetimeIndex,
    *,
    n_per_event: int,
    window: tuple[int, int],
    rng: random.Random,
    exclusion: int = EVENT_EXCLUSION,
) -> list[float]:
    """Sample matched (same-ticker, same-year) non-event CARs.

    For each event (t0 position, year) we draw up to ``n_per_event`` placebo
    anchors from the SAME calendar year on the SAME ticker, at least
    ``exclusion`` trading days from every event t0, with the window fitting.
    This is the matched (ticker, year) control of pre-reg §4 — it absorbs the
    cohort's composition drift. Pure given ``rng``.
    """

    n = len(abn)
    if n == 0:
        return []
    blocked: set[int] = set()
    for pos in event_t0_positions:
        for d in range(pos - exclusion, pos + exclusion + 1):
            blocked.add(d)

    years = pd.DatetimeIndex(index).year
    w_lo, w_hi = window
    out: list[float] = []
    for year in event_years:
        candidates = [
            p
            for p in range(-w_lo, n - w_hi)
            if p not in blocked and int(years[p]) == int(year)
        ]
        rng.shuffle(candidates)
        drawn = 0
        for pos in candidates:
            if drawn >= n_per_event:
                break
            car = window_car(abn, pos, window)
            if car is not None:
                out.append(car)
                drawn += 1
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
    sharpe: float  # mean/std of the (gross) CARs — cross-event Sharpe proxy


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


def net_vs_matched(
    event_cars: list[float],
    matched_cars: list[float],
) -> tuple[float, float]:
    """(net, Welch t) = cohort mean minus matched (ticker, year) control mean.

    The net effect strips out the same-ticker, same-year drift the cohort would
    otherwise inherit (artifact classes #5/#6).
    """

    net = mean(event_cars) - mean(matched_cars)
    return net, welch_t(event_cars, matched_cars)


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
    matched_mean: float,
    matched_t: float,
    net_vs_matched_mean: float,
    net_vs_matched_t: float,
    min_n: int = 30,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered T41 gate (ALL must hold), from brain/30.

    1. N >= ``min_n`` usable events.
    2. After-cost PRIMARY mean > 0 AND |t| >= ``t_threshold``.
    3. OOS sign stability: IS and OOS after-cost means same sign, both N >= 10.
    4. Matched placebo ~0: |matched_t| < ``t_threshold``.
    5. Net of matched control > 0 AND |net t| >= ``t_threshold``.
    Each line is reported PASS/FAIL.
    """

    reasons: list[str] = []

    enough = n_events >= min_n
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={n_events} (need >= {min_n})")

    primary_ok = after_cost_mean > 0 and abs(after_cost_t) >= t_threshold
    reasons.append(
        f"{'PASS' if primary_ok else 'FAIL'}: after-cost PRIMARY mean="
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

    placebo_null = abs(matched_t) < t_threshold
    reasons.append(
        f"{'PASS' if placebo_null else 'FAIL'}: matched placebo mean="
        f"{matched_mean:+.5f} t={matched_t:+.2f} (need |t| < {t_threshold})"
    )

    survives = net_vs_matched_mean > 0 and abs(net_vs_matched_t) >= t_threshold
    reasons.append(
        f"{'PASS' if survives else 'FAIL'}: net vs matched control="
        f"{net_vs_matched_mean:+.5f} t={net_vs_matched_t:+.2f} "
        f"(need > 0 and |t| >= {t_threshold})"
    )

    return GateVerdict(
        passed=enough and primary_ok and oos_ok and placebo_null and survives,
        reasons=reasons,
    )
