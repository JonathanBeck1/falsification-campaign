"""Event study: do S&P 500 / Nasdaq-100 ADDITIONS earn positive abnormal returns
(and DELETIONS negative) around the membership change — and has it decayed?

Pre-registered in ``research/index_rebalance_preregistration.md``. Falsify-first.

Honest prior: the index-inclusion effect was large pre-2000 (Shleifer 1986,
Harris-Gurel 1986) but has **largely decayed post-2010** as it became anticipated
and front-run (Greenwood, Bennett, Patel). We expect a weak/null effect, weaker
recently, and the OOS split is designed to *show* the decay (2010-2017 vs
2018-2025). A clean null is a win.

Design (all pre-registered):

* Event list = (ticker, effective_date) pairs for additions and, separately,
  deletions. Derived by diffing a maintained constituent-snapshot CSV (the
  ``IndexChangeProvider`` seam below; the default impl hits a GitHub raw CSV, but
  the parser ``changes_from_snapshots`` is pure and unit-tested offline).
* t0 = first trading day on/after the effective date.
* Abnormal return = stock return - SPY return (market-adjusted, beta=1; a
  deliberate conservative simplification matching the house lockup/cef studies).
* CAR windows around t0; aggregate with a one-sample t-stat; OOS/decay split.

The CAR math and the snapshot-diff parser are pure and unit-tested on synthetic
data; only ``DefaultIndexChangeProvider.fetch`` and the price loader do I/O.
"""

from __future__ import annotations

import csv
import io
import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd
import structlog

log = structlog.get_logger(__name__)

# Event-time CAR windows, trading days relative to t0 (inclusive ranges).
CAR_WINDOWS: dict[str, tuple[int, int]] = {
    "car_m5_m1": (-5, -1),   # pre-effective run-up (captures announcement ~1wk prior)
    "car_m1_p1": (-1, 1),    # the change itself
    "car_0_p5": (0, 5),
    "car_0_p21": (0, 21),    # PRIMARY horizon (~1 month)
}
NEED_LO = min(w[0] for w in CAR_WINDOWS.values())
NEED_HI = max(w[1] for w in CAR_WINDOWS.values())

# Robustness guard: a single-day market-adjusted return whose magnitude exceeds
# this is, for an S&P 500 constituent, almost certainly a yfinance data glitch
# (an unadjusted split day or a near-zero bad print), not a real index-effect
# move. Such an event is dropped (counted, not hidden). Calibrated from the data:
# exactly one 2010-2025 addition (CBE, 2011) tripped this with a +65,000% spike;
# 0.75 (=75% one-day abnormal) sits far above any plausible real move.
MAX_ABS_DAILY_AR = 0.75


# --------------------------------------------------------------------------- #
# Event list: snapshot-diff parser (pure) + provider seam (I/O, mockable)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IndexChange:
    """One membership change: a ticker added or removed, on an effective date."""

    ticker: str
    effective_date: date
    kind: str  # "add" or "delete"


def changes_from_snapshots(
    snapshots: Sequence[tuple[date, frozenset[str]]],
) -> list[IndexChange]:
    """Diff consecutive constituent snapshots into add/delete events. Pure.

    ``snapshots`` is a sequence of ``(snapshot_date, set_of_tickers)``. A ticker
    present in snapshot ``t+1`` but absent in ``t`` is an *addition* effective on
    ``t+1``; the reverse is a *deletion*. The first snapshot only seeds the
    baseline (no events). Snapshots are sorted by date internally.
    """

    snaps = sorted(snapshots, key=lambda s: s[0])
    out: list[IndexChange] = []
    for (_d0, s0), (d1, s1) in itertools.pairwise(snaps):
        for tk in sorted(s1 - s0):
            out.append(IndexChange(ticker=tk, effective_date=d1, kind="add"))
        for tk in sorted(s0 - s1):
            out.append(IndexChange(ticker=tk, effective_date=d1, kind="delete"))
    return out


def parse_snapshot_csv(text: str) -> list[tuple[date, frozenset[str]]]:
    """Parse a ``date,tickers`` CSV (tickers comma-joined in one quoted field).

    This is the format of fja05680/sp500 *"Historical Components & Changes"*. Pure.
    """

    rows = list(csv.reader(io.StringIO(text)))
    out: list[tuple[date, frozenset[str]]] = []
    for row in rows[1:]:  # skip header
        if len(row) < 2 or not row[0]:
            continue
        try:
            d = date.fromisoformat(row[0].strip())
        except ValueError:
            continue
        tickers = frozenset(t.strip() for t in row[1].split(",") if t.strip())
        if tickers:
            out.append((d, tickers))
    return out


class IndexChangeProvider(Protocol):
    """Seam for fetching the constituent-snapshot text. Mockable in tests."""

    def fetch(self) -> str: ...


@dataclass(frozen=True)
class DefaultIndexChangeProvider:
    """Fetches the maintained S&P 500 constituent-snapshot CSV from GitHub."""

    url: str = (
        "https://raw.githubusercontent.com/fja05680/sp500/master/"
        "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
    )
    timeout: float = 60.0

    def fetch(self) -> str:
        import httpx

        log.info("index_rebalance.fetch_snapshots", url=self.url)
        resp = httpx.get(self.url, timeout=self.timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text


def load_changes(provider: IndexChangeProvider | None = None) -> list[IndexChange]:
    """Fetch + parse + diff into a list of IndexChange events (best-effort I/O)."""

    provider = provider or DefaultIndexChangeProvider()
    snaps = parse_snapshot_csv(provider.fetch())
    changes = changes_from_snapshots(snaps)
    log.info(
        "index_rebalance.changes",
        n=len(changes),
        adds=sum(c.kind == "add" for c in changes),
        deletes=sum(c.kind == "delete" for c in changes),
    )
    return changes


# --------------------------------------------------------------------------- #
# CAR math (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EventMetrics:
    """Per-event market-adjusted CARs in event time."""

    ticker: str
    event_date: date     # the effective date used as input
    t0_date: date        # resolved t0 trading day
    kind: str            # "add" or "delete"
    car_m5_m1: float
    car_m1_p1: float
    car_0_p5: float
    car_0_p21: float


@dataclass(frozen=True)
class WindowAgg:
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
    windows: dict[str, WindowAgg]


# sorted_close is shared (trader.research.event_study); aliased so call sites are
# unchanged. Byte-identical to the former local copy.
from trader.research.event_study import sorted_close as _sorted_close  # noqa: E402


def compute_event_metrics(
    close: pd.Series,
    spy_close: pd.Series,
    event_date: date,
    *,
    kind: str,
    offset_trading_days: int = 0,
) -> EventMetrics | None:
    """Compute one event's market-adjusted CARs, or ``None`` if data is too thin.

    ``close`` is the single stock's daily close; ``spy_close`` is SPY's. t0 = first
    trading day on/after ``event_date`` (shifted by ``offset_trading_days``).
    Returns ``None`` when the full ``[NEED_LO, NEED_HI]`` window around t0 isn't
    present (e.g. a deletion whose ticker was purged shortly after).
    """

    close = _sorted_close(close)
    if len(close) < (NEED_HI - NEED_LO + 2):
        return None

    dates = close.index
    pos = int(dates.searchsorted(pd.Timestamp(event_date), side="left"))
    t0 = pos + offset_trading_days
    if t0 < 0 or t0 >= len(dates):
        return None
    if t0 + NEED_LO < 0 or t0 + NEED_HI >= len(dates):
        return None

    ret = close.pct_change()
    spy = _sorted_close(spy_close).reindex(dates).ffill()
    ar = ret - spy.pct_change()  # market-adjusted abnormal return (beta=1)

    # Drop the event if any single-day abnormal return inside the widest window is
    # absurd (split/data glitch). Counted as missing by the caller, never hidden.
    win = ar.iloc[t0 + NEED_LO : t0 + NEED_HI + 1]
    if (win.abs() > MAX_ABS_DAILY_AR).any():
        return None

    def _car(a: int, b: int) -> float:
        seg = ar.iloc[t0 + a : t0 + b + 1]
        return float(seg.sum())

    return EventMetrics(
        ticker=str(close.name) if close.name else "",
        event_date=event_date,
        t0_date=dates[t0].date(),
        kind=kind,
        car_m5_m1=_car(*CAR_WINDOWS["car_m5_m1"]),
        car_m1_p1=_car(*CAR_WINDOWS["car_m1_p1"]),
        car_0_p5=_car(*CAR_WINDOWS["car_0_p5"]),
        car_0_p21=_car(*CAR_WINDOWS["car_0_p21"]),
    )


# t_stat is shared (trader.research.gate); aliased so call sites are unchanged.
# Byte-identical to the former local copy (ddof=1, 0.0 on N<2 / zero variance).
from trader.research.gate import t_stat as _t_stat  # noqa: E402


def _agg(metric: str, values: list[float]) -> WindowAgg:
    vals = [v for v in values if v == v]
    n = len(vals)
    if n == 0:
        return WindowAgg(metric, 0, float("nan"), float("nan"), float("nan"), 0.0)
    s = pd.Series(vals)
    return WindowAgg(
        metric=metric,
        n=n,
        mean=float(s.mean()),
        median=float(s.median()),
        pct_positive=float((s > 0).mean()),
        t_stat=_t_stat(vals),
    )


def aggregate(metrics: list[EventMetrics], *, label: str) -> StudyResult:
    """Aggregate per-event CARs into mean/median/%pos/t-stat per window."""

    windows = {
        name: _agg(name, [getattr(m, name) for m in metrics]) for name in CAR_WINDOWS
    }
    return StudyResult(label=label, n_events=len(metrics), windows=windows)


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: list[str]


def evaluate_gate(
    real: StudyResult,
    oos_early: StudyResult,
    oos_late: StudyResult,
    *,
    min_events: int = 30,
    primary: str = "car_0_p21",
    t_threshold: float = 2.0,
) -> GateVerdict:
    """Pre-registered ADDITIONS gate (ALL must hold):

    N>=min_events; primary CAR positive with |t|>=t_threshold; same sign OOS. The
    decay comparison is reported separately by the runner regardless of pass/fail.
    """

    reasons: list[str] = []
    car = real.windows[primary]

    enough = real.n_events >= min_events
    reasons.append(
        f"{'PASS' if enough else 'FAIL'}: N={real.n_events} (need >= {min_events})"
    )

    sig = (car.mean > 0) and (abs(car.t_stat) >= t_threshold)
    reasons.append(
        f"{'PASS' if sig else 'FAIL'}: signal — {primary} mean={car.mean:+.4f} "
        f"t={car.t_stat:+.2f} (need >0 & |t|>={t_threshold})"
    )

    early, late = oos_early.windows[primary].mean, oos_late.windows[primary].mean
    same_sign = (early > 0 and late > 0) or (early < 0 and late < 0)
    reasons.append(
        f"{'PASS' if same_sign else 'FAIL'}: OOS sign stable — "
        f"early={early:+.4f} late={late:+.4f} (need same sign)"
    )

    return GateVerdict(passed=enough and sig and same_sign, reasons=reasons)
