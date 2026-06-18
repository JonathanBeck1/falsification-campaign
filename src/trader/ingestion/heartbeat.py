"""Data-freshness tracking and staleness gate.

A "heartbeat" here is a regular signal that a data source is alive and
producing fresh items. Polled adapters don't have an inherent heartbeat
the way WebSockets do; we synthesize one by recording every fetch
attempt (success or empty) and consulting the timestamps before any
LLM-using brain runs.

The gate is conservative: if ALL configured news sources have gone
stale beyond their per-source budget, we refuse to run any LLM-using
brain for that cycle. Deterministic brains (ClassicalBrain,
BuyAndHoldBrain, SentimentMomentumBrain reading historical events)
are unaffected — they're allowed to operate on the existing snapshot.

Per `brain/22`'s honest-latency framing: free-tier polling cadences
sit at 10-30s for most sources. If a source's heartbeat is older than
its budget, the data is stale enough that any LLM call would be
acting on possibly-misleading state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog

log = structlog.get_logger()

# Per-source freshness budgets in minutes. Numbers reflect the realistic
# polling cadence each adapter can deliver on free tier + a 3x safety
# multiplier for network jitter.
DEFAULT_FRESHNESS_BUDGETS_MIN: dict[str, int] = {
    "finnhub": 30,
    "alpaca_news": 30,
    "yahoo_news": 60,
    "sec_edgar": 240,  # SEC filings are infrequent
    "fed": 1440,  # Fed RSS updates 0-2x/day
    "web_news": 60,
}


@dataclass
class SourceHealth:
    """In-memory health record for one adapter. Reset per run."""

    source: str
    last_fetch_at: datetime | None = None
    last_item_count: int = 0
    consecutive_empty_fetches: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class FreshnessVerdict:
    """Output of the gate: should the LLM path run this cycle?"""

    all_stale: bool
    stale_sources: tuple[str, ...]
    fresh_sources: tuple[str, ...]
    note: str

    @property
    def should_skip_llm(self) -> bool:
        return self.all_stale


class HeartbeatTracker:
    """Tracks per-source freshness for one run of the pipeline.

    Each adapter calls `record_fetch` with the count of items returned.
    Before brains run, the runner calls `evaluate` to decide whether
    LLM-using brains should be allowed.
    """

    def __init__(
        self,
        *,
        budgets_min: dict[str, int] | None = None,
        now_fn=None,
    ) -> None:
        self._budgets = dict(budgets_min or DEFAULT_FRESHNESS_BUDGETS_MIN)
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._health: dict[str, SourceHealth] = {}

    def record_fetch(
        self,
        source: str,
        *,
        item_count: int,
        error: str | None = None,
    ) -> None:
        """Record that `source` was queried. `item_count=0` is a successful
        fetch with no new data — still counts as a heartbeat. `error` means
        the fetch failed entirely (no heartbeat)."""
        existing = self._health.get(source)
        if error is not None:
            if existing is None:
                self._health[source] = SourceHealth(source=source, last_error=error)
            else:
                existing.last_error = error
            return

        consecutive = 0 if item_count > 0 else (existing.consecutive_empty_fetches + 1 if existing else 1)
        self._health[source] = SourceHealth(
            source=source,
            last_fetch_at=self._now(),
            last_item_count=item_count,
            consecutive_empty_fetches=consecutive,
            last_error=None,
        )

    def evaluate(self, *, required_sources: list[str] | None = None) -> FreshnessVerdict:
        """Decide whether the LLM path should be gated. A source is stale if
        its last successful fetch is older than its budget OR it has never
        fetched successfully this run."""
        sources = required_sources or list(self._budgets.keys())
        now = self._now()
        stale: list[str] = []
        fresh: list[str] = []
        notes: list[str] = []

        for source in sources:
            budget_min = self._budgets.get(source, 60)
            h = self._health.get(source)
            if h is None or h.last_fetch_at is None:
                stale.append(source)
                notes.append(f"{source}=no_heartbeat")
                continue
            age = now - h.last_fetch_at
            if age > timedelta(minutes=budget_min):
                stale.append(source)
                notes.append(f"{source}=stale({int(age.total_seconds() / 60)}m>{budget_min}m)")
            else:
                fresh.append(source)

        all_stale = len(fresh) == 0
        return FreshnessVerdict(
            all_stale=all_stale,
            stale_sources=tuple(stale),
            fresh_sources=tuple(fresh),
            note="; ".join(notes) if notes else "all_sources_fresh",
        )


def gate_llm_brains_on_freshness(
    tracker: HeartbeatTracker, *, required_sources: list[str] | None = None
) -> FreshnessVerdict:
    """Convenience wrapper. The runner calls this; if the verdict says
    `should_skip_llm`, HybridBrain and any future LLM-using brain is
    skipped for this cycle. Deterministic brains run as normal."""
    verdict = tracker.evaluate(required_sources=required_sources)
    if verdict.should_skip_llm:
        log.warning(
            "data_freshness_gate_tripped_skipping_llm_brains",
            stale_sources=verdict.stale_sources,
            note=verdict.note,
        )
    return verdict


# Sentinel used in tests that want to fast-forward the clock.
@dataclass
class _FrozenClock:
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now = self.now + timedelta(minutes=minutes)
