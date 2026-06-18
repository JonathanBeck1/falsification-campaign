"""MacroEventBrain — Fed-only deterministic macro signal.

Reads Fed press releases from `news_events` (source="federalreserve.gov",
event_type="fed_commentary"), aggregates sentiment with exponential recency
decay, and returns a target position weight. Two variants ship in Phase 2:

- **Conservative**: 90-day lookback, requires either 2 same-direction events
  or one breaking+credible single event, |aggregate sentiment| >= 0.30.
- **Aggressive**: 14-day lookback, single event with |sentiment| >= 0.20 is
  enough, |aggregate sentiment| >= 0.10.

Per `brain/decisions/2026-05-21-horse-race-phase-2.md`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trader.normalization.models import Event
from trader.signals.base import Decision
from trader.storage.snapshot import DailySnapshot
from trader.storage.store import Store

FED_SOURCE = "federalreserve.gov"
FED_EVENT_TYPE = "fed_commentary"

# Credibility floor for the "breaking + credible single event" shortcut.
BREAKING_SHORTCUT_CREDIBILITY_FLOOR = 0.8


@dataclass(frozen=True)
class _FedContribution:
    sentiment: float
    weight: float
    urgency: str
    credibility: float
    age_days: float


class MacroEventBrain:
    """Fed-only macro brain. Deterministic, no LLM."""

    uses_llm = False

    def __init__(
        self,
        *,
        store: Store,
        lookback_days: int,
        recency_half_life_days: float,
        min_events_for_signal: int,
        buy_threshold: float,
        sell_threshold: float,
        target_long: float,
        target_short: float,
        neutral_target: float,
        require_multi_event_confirmation: bool,
        name: str,
    ) -> None:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if recency_half_life_days <= 0:
            raise ValueError("recency_half_life_days must be positive")
        if min_events_for_signal < 1:
            raise ValueError("min_events_for_signal must be >= 1")
        if buy_threshold <= 0:
            raise ValueError("buy_threshold must be > 0")
        if sell_threshold >= 0:
            raise ValueError("sell_threshold must be < 0")
        for label, value in (
            ("target_long", target_long),
            ("target_short", target_short),
            ("neutral_target", neutral_target),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be in [0, 1]")

        self._store = store
        self._lookback_days = lookback_days
        self._recency_half_life_days = recency_half_life_days
        self._min_events_for_signal = min_events_for_signal
        self._buy_threshold = buy_threshold
        self._sell_threshold = sell_threshold
        self._target_long = target_long
        self._target_short = target_short
        self._neutral_target = neutral_target
        self._require_multi_event_confirmation = require_multi_event_confirmation
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        now = _snapshot_time(snapshot)
        since = now - timedelta(days=self._lookback_days)

        # Filter on source + event_type at the query layer so we only ever
        # consider Fed press-release rows. Defensive belt: re-filter in-memory
        # to be robust against any future loosening of get_news_events_parsed.
        events = [
            e
            for e in self._store.get_news_events_parsed(
                since=since,
                until=now + timedelta(microseconds=1),
                source=FED_SOURCE,
                event_type=FED_EVENT_TYPE,
                limit=10_000,
            )
            if e.source == FED_SOURCE and e.event_type == FED_EVENT_TYPE
        ]

        if len(events) < self._min_events_for_signal:
            return Decision(
                action="HOLD",
                target_pct=self._neutral_target,
                confidence=0.3,
                reasoning=(
                    f"no recent Fed activity ({len(events)} events in last "
                    f"{self._lookback_days}d, need {self._min_events_for_signal})"
                ),
            )

        contributions = [self._contribution_for(e, now) for e in events]
        total_weight = sum(c.weight for c in contributions)
        if total_weight == 0:
            return Decision(
                action="HOLD",
                target_pct=self._neutral_target,
                confidence=0.3,
                reasoning=f"zero total weight across {len(events)} Fed events",
            )

        aggregate = sum(c.sentiment * c.weight for c in contributions) / total_weight
        bullish = aggregate > self._buy_threshold
        bearish = aggregate < self._sell_threshold

        if not (bullish or bearish):
            return Decision(
                action="HOLD",
                target_pct=self._neutral_target,
                confidence=0.4,
                reasoning=(
                    f"Fed aggregate {aggregate:+.2f} in [{self._sell_threshold:+.2f}, "
                    f"{self._buy_threshold:+.2f}] -> HOLD @ {self._neutral_target:.0%}"
                ),
            )

        # Confirming-check (the "data interpretation" dial).
        confirmed, confirm_reason = self._confirm(contributions, bullish=bullish)
        if not confirmed:
            return Decision(
                action="HOLD",
                target_pct=self._neutral_target,
                confidence=0.4,
                reasoning=(
                    f"Fed aggregate {aggregate:+.2f} crossed threshold but "
                    f"confirmation failed: {confirm_reason}"
                ),
            )

        if bullish:
            return Decision(
                action="BUY",
                target_pct=self._target_long,
                confidence=0.75,
                reasoning=(
                    f"Fed aggregate {aggregate:+.2f} >= {self._buy_threshold:+.2f}, "
                    f"{confirm_reason} -> BUY @ {self._target_long:.0%}"
                ),
            )
        return Decision(
            action="SELL",
            target_pct=self._target_short,
            confidence=0.75,
            reasoning=(
                f"Fed aggregate {aggregate:+.2f} <= {self._sell_threshold:+.2f}, "
                f"{confirm_reason} -> SELL @ {self._target_short:.0%}"
            ),
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _contribution_for(self, event: Event, now: datetime) -> _FedContribution:
        urgency_w = _URGENCY_WEIGHTS.get(event.urgency, 0.4)
        credibility = max(0.0, min(1.0, event.source_credibility))
        age_days = max(0.0, (now - event.published_at).total_seconds() / 86400.0)
        recency_w = math.exp(-age_days * math.log(2) / self._recency_half_life_days)
        sentiment = max(-1.0, min(1.0, event.sentiment_score))
        weight = urgency_w * credibility * recency_w
        return _FedContribution(
            sentiment=sentiment,
            weight=weight,
            urgency=event.urgency,
            credibility=credibility,
            age_days=age_days,
        )

    def _confirm(
        self, contributions: list[_FedContribution], *, bullish: bool
    ) -> tuple[bool, str]:
        """Variant-specific confirmation check on the aggregate signal."""
        if not self._require_multi_event_confirmation:
            return True, "single-event confirmation (Aggressive)"

        # Conservative path: either >=2 same-direction events OR one breaking+credible.
        same_direction = [
            c
            for c in contributions
            if (c.sentiment > 0) == bullish and abs(c.sentiment) >= 0.1
        ]
        if len(same_direction) >= 2:
            return True, f"{len(same_direction)} same-direction events confirm"

        breaking_credible = [
            c
            for c in contributions
            if c.urgency == "breaking" and c.credibility >= BREAKING_SHORTCUT_CREDIBILITY_FLOOR
        ]
        if breaking_credible:
            return True, "breaking+credible single event confirms"
        return False, "needed 2 same-direction events or breaking+credible"


_URGENCY_WEIGHTS: dict[str, float] = {
    "breaking": 1.0,
    "high": 0.7,
    "normal": 0.4,
    "low": 0.2,
}


def _snapshot_time(snapshot: DailySnapshot) -> datetime:
    ts = snapshot.latest_bar.timestamp
    if ts.tzinfo is None or ts.utcoffset() is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def macro_event_conservative(*, store: Store, name: str = "MacroEventConservative") -> MacroEventBrain:
    return MacroEventBrain(
        store=store,
        lookback_days=90,
        recency_half_life_days=14.0,
        min_events_for_signal=1,
        buy_threshold=0.30,
        sell_threshold=-0.30,
        target_long=0.60,
        target_short=0.00,
        neutral_target=0.40,
        require_multi_event_confirmation=True,
        name=name,
    )


def macro_event_aggressive(*, store: Store, name: str = "MacroEventAggressive") -> MacroEventBrain:
    return MacroEventBrain(
        store=store,
        lookback_days=14,
        recency_half_life_days=3.0,
        min_events_for_signal=1,
        buy_threshold=0.10,
        sell_threshold=-0.10,
        target_long=1.00,
        target_short=0.00,
        neutral_target=0.50,
        require_multi_event_confirmation=False,
        name=name,
    )
