"""Event-window study per `brain/09_backtesting_and_validation.md`.

For each `Event` in the `news_events` table, compute the benchmark ticker's
forward return at multiple horizons after the event's `observed_at`.
Aggregate by `event_type` to expose distribution stats: hit rate, mean,
median, dispersion, tails.

This is research, not paper trading. The point is to answer the brain/09
question: "does event class X correlate with a directional move at horizon Y,
out-of-sample, with realistic spreads?" If yes, that's evidence to consider a
signal. If no, the class earns nothing and shouldn't drive trades.

Inputs come from two places:
- `Event` records via `Store.get_news_events_parsed()`
- intraday bars via `adapters/alpaca/market.fetch_intraday_bars()`
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median, stdev

from trader.normalization.models import Event
from trader.storage.snapshot import Bar

DEFAULT_HORIZONS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "5d": timedelta(days=5),
}


@dataclass(frozen=True)
class WindowResult:
    """Per-event, per-horizon forward-return record."""

    event_id: str
    event_type: str
    benchmark: str
    horizon: str
    observed_at: datetime
    price_at_event: float
    price_at_horizon: float
    return_pct: float


@dataclass
class HorizonStats:
    """Aggregated distribution stats for one (event_type, horizon) cell."""

    event_type: str
    horizon: str
    n: int
    hit_rate: float
    mean_return_pct: float
    median_return_pct: float
    stdev_return_pct: float
    min_return_pct: float
    max_return_pct: float


def _price_at_or_after(bars: list[Bar], ts: datetime) -> float | None:
    """Close price of the first bar with timestamp >= `ts`. None if past last bar.

    `bars` must already be sorted by timestamp ascending.
    """
    if not bars:
        return None
    timestamps = [b.timestamp for b in bars]
    idx = bisect_left(timestamps, ts)
    if idx >= len(bars):
        return None
    return bars[idx].close


def compute_event_returns(
    events: list[Event],
    bars: list[Bar],
    *,
    benchmark: str = "SPY",
    horizons: dict[str, timedelta] | None = None,
) -> list[WindowResult]:
    """For each (event, horizon) pair, compute forward return.

    Events with no price coverage (before earliest bar or after latest) are
    silently skipped. `bars` must be sorted by timestamp ascending.
    """
    horizons_ = horizons or DEFAULT_HORIZONS
    out: list[WindowResult] = []
    for event in events:
        event_ts = event.observed_at
        px_event = _price_at_or_after(bars, event_ts)
        if px_event is None or px_event == 0:
            continue
        for hname, delta in horizons_.items():
            px_target = _price_at_or_after(bars, event_ts + delta)
            if px_target is None:
                continue
            out.append(
                WindowResult(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    benchmark=benchmark,
                    horizon=hname,
                    observed_at=event_ts,
                    price_at_event=px_event,
                    price_at_horizon=px_target,
                    return_pct=(px_target - px_event) / px_event * 100.0,
                )
            )
    return out


def aggregate_by_type(results: list[WindowResult]) -> list[HorizonStats]:
    """Group results by (event_type, horizon) and compute distribution stats.

    `hit_rate` here means "fraction of windows with strictly positive return."
    That's directional bias, not a profitable-strategy claim.
    """
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in results:
        buckets[(r.event_type, r.horizon)].append(r.return_pct)
    out: list[HorizonStats] = []
    for (etype, horizon), returns in sorted(buckets.items()):
        if not returns:
            continue
        out.append(
            HorizonStats(
                event_type=etype,
                horizon=horizon,
                n=len(returns),
                hit_rate=sum(1 for r in returns if r > 0) / len(returns),
                mean_return_pct=mean(returns),
                median_return_pct=median(returns),
                stdev_return_pct=stdev(returns) if len(returns) > 1 else 0.0,
                min_return_pct=min(returns),
                max_return_pct=max(returns),
            )
        )
    return out


def format_report(
    stats: list[HorizonStats],
    *,
    benchmark: str = "SPY",
    metadata: dict[str, object] | None = None,
) -> str:
    """Render aggregated stats as a markdown table.

    The point of the report is to make it obvious WHICH cells have enough N
    to take seriously and WHICH are noise. Low-N rows are still shown but the
    reader should treat them with appropriate skepticism.
    """
    lines = [
        f"# Event-Window Study: {benchmark}",
        "",
        "Per `brain/09_backtesting_and_validation.md`. Hit rate = fraction of",
        "windows with strictly positive return. Low N → noisy estimate.",
        "",
    ]
    if metadata:
        lines.extend(["## Run Metadata", ""])
        for key in sorted(metadata):
            lines.append(f"- {key}: {metadata[key]}")
        lines.append("")
    lines.extend(
        [
            "| event_type | horizon | n | hit_rate | mean% | median% | stdev% | min% | max% |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for s in stats:
        lines.append(
            f"| {s.event_type} | {s.horizon} | {s.n} | "
            f"{s.hit_rate:.0%} | {s.mean_return_pct:+.2f} | "
            f"{s.median_return_pct:+.2f} | {s.stdev_return_pct:.2f} | "
            f"{s.min_return_pct:+.2f} | {s.max_return_pct:+.2f} |"
        )
    return "\n".join(lines) + "\n"
