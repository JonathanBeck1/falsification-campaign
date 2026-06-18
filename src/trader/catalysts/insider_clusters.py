"""Event study: do CLUSTERS of insider open-market buys predict forward returns?

Pre-registered in ``research/insider_cluster_preregistration.md``. The thesis
(best-documented insider signal in the literature, hence likely decayed): when
``>= K`` distinct insiders of the same issuer file Form-4 OPEN-MARKET PURCHASES
(transaction code ``P``) within a short calendar window (a "cluster"), the stock
earns positive **market-adjusted** CAR (stock return minus SPY, beta=1) over the
following 1/3/6/12 months.

This module is PURE and unit-tested on synthetic data; no network, no I/O. It
provides:

* :func:`build_clusters` — group raw Form-4 ``P`` transactions into clusters per
  issuer (``>= K`` distinct insiders within ``window_days``), anchored on the
  LAST buy in the cluster (the conservative, no-look-ahead entry).
* :func:`compute_event_metrics` — market-adjusted CAR over the pre-registered
  windows for one event, or ``None`` if data is insufficient.
* :func:`aggregate` / :func:`evaluate_gate` — house-style mean/median/%pos/t-stat
  aggregation and the pre-registered pass/fail gate (matches ``lockup_study`` /
  ``cef_study``).

Design choices (all pre-registered):

* Beta=1 market adjustment (stock minus SPY), the same deliberate simplification
  used in ``lockup_study.py``.
* Event date = the latest buy date in the cluster. A follower cannot trade until
  the final qualifying buy is on the tape.
* CAR over ``[0, +h]`` is the sum of daily abnormal returns from t0 through t0+h
  in trading days. Events require the full ``[0, +252]`` window so the same N is
  used for every horizon (no horizon-dependent survivorship).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import structlog

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


@dataclass(frozen=True)
class InsiderBuy:
    """One Form-4 open-market purchase (transaction code 'P')."""

    cik: str            # issuer CIK (the dedup key for an issuer)
    ticker: str
    issuer: str
    insider: str        # reporting-owner name (raw)
    trade_date: date    # transaction date (NOT the filing date)
    shares: float
    price: float


@dataclass(frozen=True)
class Cluster:
    """A detected insider-buy cluster for one issuer."""

    cik: str
    ticker: str
    issuer: str
    event_date: date            # the LAST buy date in the cluster (the anchor)
    first_date: date            # the first buy date in the cluster
    n_distinct_insiders: int
    n_buys: int
    total_shares: float
    total_value: float          # sum(shares*price); 0 if prices missing
    insiders: tuple[str, ...]   # normalized distinct insider names


@dataclass(frozen=True)
class EventMetrics:
    """Per-event market-adjusted CARs in event time."""

    cik: str
    ticker: str
    event_date: date
    t0_date: date
    n_distinct_insiders: int
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


def normalize_insider(name: str) -> str:
    """Normalize a reporting-owner name for distinct-insider counting."""

    return " ".join(str(name).strip().upper().split())


# --------------------------------------------------------------------------- #
# Cluster detection (pure)
# --------------------------------------------------------------------------- #
def build_clusters(
    buys: list[InsiderBuy],
    *,
    k_distinct: int = 2,
    window_days: int = 30,
    merge_days: int = 30,
) -> list[Cluster]:
    """Group ``P`` purchases into clusters per issuer.

    A cluster requires ``>= k_distinct`` DISTINCT insiders (by normalized name)
    whose buys all fall inside a rolling ``window_days``-calendar-day span. The
    event date is the LAST buy in the qualifying span. After a cluster fires,
    buys within ``merge_days`` of that event date are absorbed (no overlapping
    double-counts of the same buying wave).

    Pure: deterministic given inputs; no network/I-O.
    """

    by_issuer: dict[str, list[InsiderBuy]] = {}
    for b in buys:
        by_issuer.setdefault(b.cik, []).append(b)

    clusters: list[Cluster] = []
    for cik, issuer_buys in by_issuer.items():
        issuer_buys = sorted(issuer_buys, key=lambda b: b.trade_date)
        used_until: date | None = None  # absorb window high-water mark

        n = len(issuer_buys)
        i = 0
        while i < n:
            anchor = issuer_buys[i]
            if used_until is not None and anchor.trade_date <= used_until:
                i += 1
                continue
            # gather all buys within [anchor, anchor+window_days]
            hi = anchor.trade_date + timedelta(days=window_days)
            span = [
                b for b in issuer_buys
                if anchor.trade_date <= b.trade_date <= hi
            ]
            distinct = {normalize_insider(b.insider) for b in span}
            if len(distinct) >= k_distinct:
                event_date = max(b.trade_date for b in span)
                # absorb any further buys within merge_days of the event date
                absorb_hi = event_date + timedelta(days=merge_days)
                span = [
                    b for b in issuer_buys
                    if anchor.trade_date <= b.trade_date <= absorb_hi
                ]
                distinct = {normalize_insider(b.insider) for b in span}
                event_date = max(b.trade_date for b in span)
                total_value = sum(
                    b.shares * b.price for b in span
                    if b.shares == b.shares and b.price == b.price
                )
                clusters.append(
                    Cluster(
                        cik=cik,
                        ticker=anchor.ticker,
                        issuer=anchor.issuer,
                        event_date=event_date,
                        first_date=min(b.trade_date for b in span),
                        n_distinct_insiders=len(distinct),
                        n_buys=len(span),
                        total_shares=sum(b.shares for b in span if b.shares == b.shares),
                        total_value=float(total_value),
                        insiders=tuple(sorted(distinct)),
                    )
                )
                used_until = absorb_hi
            i += 1

    clusters.sort(key=lambda c: (c.event_date, c.ticker))
    log.info(
        "clusters_built",
        n_buys=len(buys),
        n_issuers=len(by_issuer),
        n_clusters=len(clusters),
        k_distinct=k_distinct,
        window_days=window_days,
    )
    return clusters


# --------------------------------------------------------------------------- #
# CAR computation (pure)
# --------------------------------------------------------------------------- #
def _sorted_close(series: pd.Series) -> pd.Series:
    s = series.dropna().sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def compute_event_metrics(
    close: pd.Series,
    spy_close: pd.Series,
    cluster: Cluster,
    *,
    event_date: date | None = None,
) -> EventMetrics | None:
    """Market-adjusted CARs for one cluster event, or ``None`` if insufficient.

    ``close`` is the stock's daily adjusted close (indexed by date); ``spy_close``
    is SPY's. ``event_date`` overrides ``cluster.event_date`` (used for placebos).
    Returns ``None`` unless the full ``[0, +252]`` trading-day window exists.
    """

    ev = event_date or cluster.event_date
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
        cik=cluster.cik,
        ticker=cluster.ticker,
        event_date=ev,
        t0_date=dates[t0].date(),
        n_distinct_insiders=cluster.n_distinct_insiders,
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


def aggregate(metrics: list[EventMetrics], *, label: str) -> StudyResult:
    """Aggregate per-event CARs into mean/median/%pos/t-stat per window."""

    stats = {
        name: _stat(name, [getattr(m, name) for m in metrics]) for name in CAR_WINDOWS
    }
    return StudyResult(label=label, n_events=len(metrics), stats=stats)


# --------------------------------------------------------------------------- #
# After-cost adjustment + robustness (pure)
# --------------------------------------------------------------------------- #
def after_cost_metrics(
    metrics: list[EventMetrics], *, round_trip: float
) -> list[EventMetrics]:
    """Subtract a single ``round_trip`` cost (e.g. 0.0040 = 40 bps) from every
    CAR window of every event. One round trip per event (one holding period).

    Returns NEW EventMetrics; pre-registered as the only ranked adjustment.
    """

    out: list[EventMetrics] = []
    for m in metrics:
        out.append(
            EventMetrics(
                cik=m.cik,
                ticker=m.ticker,
                event_date=m.event_date,
                t0_date=m.t0_date,
                n_distinct_insiders=m.n_distinct_insiders,
                car_0_p21=m.car_0_p21 - round_trip,
                car_0_p63=m.car_0_p63 - round_trip,
                car_0_p126=m.car_0_p126 - round_trip,
                car_0_p252=m.car_0_p252 - round_trip,
            )
        )
    return out


def drop_top_contributors(
    metrics: list[EventMetrics], *, k: int, by: str = PRIMARY
) -> list[EventMetrics]:
    """Return ``metrics`` with the ``k`` largest events (by ``by`` window)
    removed — the pre-registered concentration check. If dropping the top-k
    flips a positive result to <=0, the effect was outlier/multibagger-driven
    (survivorship artifact), not a broad signal.
    """

    if k <= 0 or k >= len(metrics):
        return list(metrics) if k <= 0 else []
    ordered = sorted(metrics, key=lambda m: getattr(m, by), reverse=True)
    drop_ids = {id(m) for m in ordered[:k]}
    return [m for m in metrics if id(m) not in drop_ids]


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
    """Pre-registered gate (ALL must hold). The ``real``/``placebo``/``oos_*``
    results passed in are the **after-cost** aggregates — the gate ranks only the
    after-cost expectancy (see ``after_cost_metrics``).

    1. N >= ``min_events`` cluster events.
    2. Primary CAR mean > 0 with ``|t| >= t_threshold``.
    3. Beats placebo on the primary window (real mean > placebo mean).
    4. OOS sign stable on the primary window across the IS/OOS split, with
       BOTH halves N >= ``min_oos_events``.
    """

    reasons: list[str] = []
    car = real.stats[primary]

    enough = real.n_events >= min_events
    reasons.append(f"{'PASS' if enough else 'FAIL'}: N={real.n_events} (need >= {min_events})")

    sig = (car.mean > 0) and (abs(car.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: after-cost primary {primary} mean={car.mean:+.4f} "
        f"t={car.t_stat:+.2f} (need >0 & |t|>={t_threshold})"
    )

    # Placebo line matches the pre-registration and the sibling event studies
    # (spinoff/buyback): the cohort must beat the placebo AND the placebo must be
    # null (|t| < threshold). "Real > placebo" alone passes vacuously when both are
    # negative — the divergence an adversarial review flagged.
    p_car = placebo.stats[primary]
    placebo_null = abs(p_car.t_stat) < t_threshold
    beats_placebo = (car.mean > p_car.mean) and placebo_null
    reasons.append(
        f"{'PASS' if beats_placebo else 'FAIL'}: beats placebo — real {primary} mean={car.mean:+.4f} "
        f"vs placebo mean={p_car.mean:+.4f} (t={p_car.t_stat:+.2f}) "
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
