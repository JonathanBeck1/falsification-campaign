"""Event study: does cloning 13F-disclosed NEW positions (from the FILING date)
outperform?

Pre-registered in ``research/thirteenf_clone_preregistration.md``. The thesis
(the classic "follow smart money" / clone anomaly): when a well-known
institutional manager discloses a NEW equity position in a 13F-HR filing, buying
that name earns a positive **market-adjusted** CAR (stock return minus SPY,
beta=1) over the following 1/3/6/12 months.

THE STRUCTURAL KILLER, tested head-on: 13F-HR is filed up to **45 days after**
quarter-end (Rule 13f-1). The only timing a follower can actually trade is the
**filing date**, by which point the information is ~1.5 months stale on average.
This module measures CAR strictly from the filing date — never the quarter-end
``report_period`` — which is the honest ex-ante test and the reason the effect
is expected to be dead after cost.

This module is PURE and unit-tested on synthetic data; no network, no I/O. It
provides:

* :func:`new_positions` — given the current and prior 13F holdings (by CUSIP),
  return the CUSIPs that are NEW this filing (absent from the prior filing).
* :func:`build_clone_events` — turn a manager's chronologically-ordered filings
  into clone events anchored on each filing's FILING date, deduplicated to one
  event per (ticker, filing_date).
* :func:`compute_event_metrics` — market-adjusted CAR over the pre-registered
  windows for one event, or ``None`` if price data is insufficient.
* :func:`aggregate` / :func:`evaluate_gate` — house-style mean/median/%pos/t-stat
  aggregation and the pre-registered pass/fail gate (matches ``insider_clusters``
  / ``lockup_study`` / ``cef_study``).

Design choices (all pre-registered):

* Beta=1 market adjustment (stock minus SPY), the same deliberate simplification
  used across the campaign.
* Event date = the 13F ``filing_date`` (NOT ``report_period``). This is the whole
  point of the test: the only ex-ante-tradeable timing.
* CAR over ``[0, +h]`` is the sum of daily abnormal returns from t0 through t0+h
  in trading days. Events require the full ``[0, +252]`` window so the same N is
  used for every horizon (no horizon-dependent survivorship).
* Equity-long only: option/put rows (``PutCall`` set) are dropped upstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd
import structlog

from trader.research.event_study import sorted_close as _sorted_close

log = structlog.get_logger()

# Forward CAR windows, in trading days from t0 (inclusive of both ends).
CAR_WINDOWS: dict[str, tuple[int, int]] = {
    "car_0_p21": (0, 21),     # ~1 month
    "car_0_p63": (0, 63),     # ~3 months -- PRIMARY
    "car_0_p126": (0, 126),   # ~6 months
    "car_0_p252": (0, 252),   # ~12 months
}
PRIMARY = "car_0_p63"
NEED_HI = max(w[1] for w in CAR_WINDOWS.values())  # require full longest window

# Pre-registered round-trip friction (single-name liquid; 5 bps each way).
ROUND_TRIP_COST = 0.0010


@dataclass(frozen=True)
class Holding:
    """One aggregated 13F equity holding (per CUSIP, options excluded)."""

    cusip: str
    ticker: str
    issuer: str
    value: float  # USD market value reported


@dataclass(frozen=True)
class Filing:
    """A single 13F-HR filing, reduced to what the study needs."""

    cik: str
    manager: str
    filing_date: date          # ex-ante tradeable anchor (NOT report_period)
    report_period: date        # quarter-end the holdings are as-of
    holdings: tuple[Holding, ...]


@dataclass(frozen=True)
class CloneEvent:
    """A clonable NEW-position disclosure, anchored on the FILING date."""

    cik: str
    manager: str
    ticker: str
    cusip: str
    issuer: str
    filing_date: date          # event date = t0 anchor (ex-ante)
    report_period: date        # quarter-end (for diagnostics / lag measurement)
    value: float


@dataclass(frozen=True)
class EventMetrics:
    """Per-event market-adjusted CARs in event time (from the filing date)."""

    cik: str
    manager: str
    ticker: str
    filing_date: date
    t0_date: date
    car_0_p21: float
    car_0_p63: float
    car_0_p126: float
    car_0_p252: float


@dataclass(frozen=True)
class WindowStat:
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
    stats: dict[str, WindowStat]


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def normalize_cusip(cusip: str) -> str:
    """Normalize a CUSIP for set membership (uppercase, stripped)."""

    return str(cusip).strip().upper()


# --------------------------------------------------------------------------- #
# NEW-position detection (pure)
# --------------------------------------------------------------------------- #
def new_positions(
    current: list[Holding], prior: list[Holding]
) -> list[Holding]:
    """Holdings in ``current`` whose CUSIP is absent from ``prior``.

    These are the positions a follower would *newly* clone this quarter. Pure:
    deterministic given inputs; no network/I-O.
    """

    prior_cusips = {normalize_cusip(h.cusip) for h in prior}
    out = [h for h in current if normalize_cusip(h.cusip) not in prior_cusips]
    return out


# --------------------------------------------------------------------------- #
# Clone-event construction (pure)
# --------------------------------------------------------------------------- #
def build_clone_events(
    filings: list[Filing], *, min_value: float = 0.0
) -> list[CloneEvent]:
    """Build clone events from one manager's filings.

    ``filings`` are for a SINGLE manager; they are sorted by ``filing_date`` and
    each filing's NEW positions (vs the immediately-preceding filing) become
    events anchored on that filing's ``filing_date``. The first filing has no
    predecessor, so it yields no events (no "new vs prior" is defined). Positions
    with reported ``value < min_value`` are dropped (de-minimis filter).

    Pure: deterministic given inputs; no network/I-O.
    """

    if not filings:
        return []
    ordered = sorted(filings, key=lambda f: f.filing_date)
    events: list[CloneEvent] = []
    for i in range(1, len(ordered)):
        cur, prev = ordered[i], ordered[i - 1]
        for h in new_positions(list(cur.holdings), list(prev.holdings)):
            if h.value < min_value:
                continue
            if not h.ticker:
                continue
            events.append(
                CloneEvent(
                    cik=cur.cik,
                    manager=cur.manager,
                    ticker=h.ticker,
                    cusip=normalize_cusip(h.cusip),
                    issuer=h.issuer,
                    filing_date=cur.filing_date,
                    report_period=cur.report_period,
                    value=h.value,
                )
            )
    return events


def dedupe_events(events: list[CloneEvent]) -> list[CloneEvent]:
    """Collapse to one event per (ticker, filing_date).

    Multiple managers disclosing the same NEW name on the same filing date share
    one forward price path; counting them once avoids double-weighting that path.
    The retained event is the highest-value disclosure (most conviction). Stable.
    """

    best: dict[tuple[str, date], CloneEvent] = {}
    for e in events:
        key = (e.ticker, e.filing_date)
        cur = best.get(key)
        if cur is None or e.value > cur.value:
            best[key] = e
    return sorted(best.values(), key=lambda e: (e.filing_date, e.ticker))


# --------------------------------------------------------------------------- #
# CAR computation (pure)
# --------------------------------------------------------------------------- #
def compute_event_metrics(
    close: pd.Series,
    spy_close: pd.Series,
    event: CloneEvent,
    *,
    event_date: date | None = None,
) -> EventMetrics | None:
    """Market-adjusted CARs for one clone event, or ``None`` if insufficient.

    ``close`` is the stock's daily adjusted close (indexed by date); ``spy_close``
    is SPY's. ``event_date`` overrides ``event.filing_date`` (used for placebos).
    t0 is the first trading day ON/AFTER the event date. Returns ``None`` unless
    the full ``[0, +252]`` trading-day forward window exists.
    """

    ev = event_date or event.filing_date
    close = _sorted_close(close)
    if len(close) < (NEED_HI + 2):
        return None

    dates = close.index
    t0 = int(dates.searchsorted(pd.Timestamp(ev), side="left"))
    if t0 < 0 or t0 >= len(dates):
        return None
    if t0 + NEED_HI >= len(dates):
        return None

    ret = close.pct_change()
    spy = _sorted_close(spy_close).reindex(dates).ffill()
    ar = ret - spy.pct_change()  # market-adjusted abnormal return (beta=1)

    def _car(a: int, b: int) -> float:
        seg = ar.iloc[t0 + a : t0 + b + 1]
        return float(seg.sum())

    return EventMetrics(
        cik=event.cik,
        manager=event.manager,
        ticker=event.ticker,
        filing_date=ev,
        t0_date=dates[t0].date(),
        car_0_p21=_car(*CAR_WINDOWS["car_0_p21"]),
        car_0_p63=_car(*CAR_WINDOWS["car_0_p63"]),
        car_0_p126=_car(*CAR_WINDOWS["car_0_p126"]),
        car_0_p252=_car(*CAR_WINDOWS["car_0_p252"]),
    )


# --------------------------------------------------------------------------- #
# Aggregation (pure) -- matches house style
# --------------------------------------------------------------------------- #
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


def aggregate(
    metrics: list[EventMetrics], *, label: str, cost: float = 0.0
) -> StudyResult:
    """Aggregate per-event CARs into mean/median/%pos/t-stat per window.

    ``cost`` is subtracted from every event's CAR before aggregation (the
    after-cost view when ``cost = ROUND_TRIP_COST``).
    """

    stats = {
        name: _stat(name, [getattr(m, name) - cost for m in metrics])
        for name in CAR_WINDOWS
    }
    return StudyResult(label=label, n_events=len(metrics), stats=stats)


def evaluate_gate(
    real: StudyResult,
    placebo: StudyResult,
    oos_early: StudyResult,
    oos_late: StudyResult,
    *,
    min_events: int = 30,
    min_oos_events: int = 10,
    primary: str = PRIMARY,
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered gate (ALL must hold):

    1. N >= ``min_events`` clone events.
    2. Primary after-cost CAR mean > 0 with ``|t| >= t_threshold``.
    3. Beats placebo on the primary window (real mean > placebo mean) AND the
       placebo is null (|t| < threshold).
    4. OOS sign stable on the primary window across the IS/OOS split, with BOTH
       halves N >= ``min_oos_events``.

    ``real`` should already be the AFTER-COST aggregation (caller passes
    ``cost=ROUND_TRIP_COST``); the gate compares against the placebo aggregated
    the same way.
    """

    reasons: list[str] = []
    car = real.stats[primary]

    enough = real.n_events >= min_events
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: N={real.n_events} (need >= {min_events})"
    )

    sig = (car.mean > 0) and (abs(car.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: primary {primary} after-cost mean={car.mean:+.4f} "
        f"t={car.t_stat:+.2f} (need >0 & |t|>={t_threshold})"
    )

    # Placebo line aligned to the pre-registration + sibling event studies: beat
    # the placebo AND the placebo must be null (|t| < threshold). "Real > placebo"
    # alone passes vacuously against a negative placebo (adversarial-review fix).
    p_car = placebo.stats[primary]
    placebo_null = abs(p_car.t_stat) < t_threshold
    beats_placebo = (car.mean > p_car.mean) and placebo_null
    reasons.append(
        f"{'PASS' if beats_placebo else 'FAIL'}: beats placebo — real {primary} "
        f"mean={car.mean:+.4f} vs placebo mean={p_car.mean:+.4f} (t={p_car.t_stat:+.2f}) "
        f"(need real greater AND placebo null |t|<{t_threshold})"
    )

    early, late = oos_early.stats[primary].mean, oos_late.stats[primary].mean
    enough_oos = oos_early.n_events >= min_oos_events and oos_late.n_events >= min_oos_events
    same_sign = (early > 0 and late > 0) or (early < 0 and late < 0)
    oos_ok = enough_oos and same_sign
    reasons.append(
        f"{'PASS' if oos_ok else 'FAIL'}: OOS sign stable — early={early:+.4f} (n={oos_early.n_events}) "
        f"late={late:+.4f} (n={oos_late.n_events}) (need same sign & both n>={min_oos_events})"
    )

    return GateVerdict(
        passed=enough and sig and beats_placebo and oos_ok, reasons=reasons
    )
