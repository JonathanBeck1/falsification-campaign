"""SentimentMomentumBrain — deterministic, no LLM.

Consumes stored `news_events` to produce a sentiment-weighted momentum signal
for SPY/QQQ trading. The brain has no awareness of price targets, position
sizing rules, or risk gates beyond emitting a `target_pct in [0, 1]`. It is
intentionally separate from `ClassicalBrain` (technicals only) and
`HybridBrain` (LLM-extracted features) so that brain disagreement is a
meaningful signal.

Inputs (all from `news_events`):
- `sentiment_score in [-1, 1]` (populated by normalizers; later overwritten
  by the LLM enricher when it runs — this brain doesn't need to know which)
- `urgency in {low, normal, high, breaking}`
- `novelty_score in [0, 1]`
- `source_credibility in [0, 1]`
- `published_at` (for recency decay)
- `entities`, `index_exposure`, `asset_scope` (for relevance filtering)

Algorithm:
1. Pull events in the lookback window.
2. Compute per-event weight = relevance x recency x urgency x novelty x credibility.
3. Aggregate sentiment = sum(sentiment_score x weight) / sum(weight).
4. Combine with trend confirmation (SMA200 from snapshot):
   - aggregate >= buy_threshold AND price > SMA200 -> BUY @ 100%
   - aggregate >= buy_threshold AND price <= SMA200 -> BUY @ 50%
   - aggregate <= sell_threshold -> SELL @ 0%
   - otherwise -> HOLD @ existing 50% baseline
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trader.normalization.models import Event
from trader.signals.base import Decision
from trader.storage.snapshot import DailySnapshot
from trader.storage.store import Store

_URGENCY_WEIGHTS: dict[str, float] = {
    "breaking": 1.0,
    "high": 0.7,
    "normal": 0.4,
    "low": 0.2,
}


@dataclass(frozen=True)
class _EventContribution:
    sentiment_score: float
    weight: float


class SentimentMomentumBrain:
    """Deterministic sentiment-weighted momentum brain. Uses stored events."""

    uses_llm = False

    def __init__(
        self,
        *,
        store: Store,
        lookback_hours: int = 48,
        recency_half_life_hours: float = 8.0,
        buy_threshold: float = 0.15,
        sell_threshold: float = -0.15,
        min_events_for_signal: int = 3,
        credibility_floor: float = 0.0,
        name: str = "SentimentMomentumBrain",
    ) -> None:
        if not 0.0 <= credibility_floor <= 1.0:
            raise ValueError(
                f"credibility_floor must be in [0.0, 1.0]; got {credibility_floor!r}"
            )
        self.name = name
        self._store = store
        self._lookback_hours = lookback_hours
        self._recency_half_life_hours = recency_half_life_hours
        self._buy_threshold = buy_threshold
        self._sell_threshold = sell_threshold
        self._min_events_for_signal = min_events_for_signal
        self._credibility_floor = credibility_floor

    def decide(self, snapshot: DailySnapshot) -> Decision:
        now = self._snapshot_time(snapshot)
        since = now - timedelta(hours=self._lookback_hours)
        events = self._store.get_news_events_parsed(
            since=since,
            until=now + timedelta(microseconds=1),
            limit=10_000,
        )

        # Provenance filter (Codex adversarial review, 2026-05-20):
        # exclude events that haven't actually been classified — default
        # sentiment="neutral" + sentiment_score=0.0 from a normalizer that
        # didn't set anything is NOT a signal-neutral observation, it's
        # missing data. Counting them toward min_events_for_signal lets
        # an under-enriched feed look like a quorum and dilutes aggregate
        # sentiment toward zero. An event is treated as "classified" if
        # the LLM enricher has written a ModelOutputMeta (model_outputs
        # non-empty) OR a normalizer explicitly set a non-default
        # sentiment value.
        classified_events = [e for e in events if self._is_classified(e)]
        unclassified_skipped = len(events) - len(classified_events)

        contributions = [
            c for c in (self._contribution_for(e, snapshot.ticker, now) for e in classified_events) if c is not None
        ]
        relevant_count = len(contributions)

        if relevant_count < self._min_events_for_signal:
            return Decision(
                action="HOLD",
                target_pct=0.5,
                confidence=0.3,
                reasoning=(
                    f"insufficient classified events ({relevant_count} relevant in last "
                    f"{self._lookback_hours}h, need {self._min_events_for_signal}; "
                    f"{unclassified_skipped} unclassified events skipped)"
                ),
            )

        total_weight = sum(c.weight for c in contributions)
        if total_weight == 0:
            return Decision(
                action="HOLD",
                target_pct=0.5,
                confidence=0.3,
                reasoning=f"zero total weight across {relevant_count} events",
            )

        aggregate = sum(c.sentiment_score * c.weight for c in contributions) / total_weight
        trend_up = self._trend_up(snapshot)

        return self._decision_from_aggregate(
            aggregate, trend_up, relevant_count, unclassified_skipped
        )

    def _contribution_for(
        self, event: Event, ticker: str, now: datetime
    ) -> _EventContribution | None:
        if event.source_credibility < self._credibility_floor:
            return None

        relevance = self._relevance(event, ticker)
        if relevance is None:
            return None

        urgency_w = _URGENCY_WEIGHTS.get(event.urgency, 0.4)
        novelty_w = max(0.0, min(1.0, event.novelty_score))
        credibility_w = max(0.0, min(1.0, event.source_credibility))
        recency_w = self._recency_weight(event.published_at, now)

        weight = relevance * urgency_w * novelty_w * credibility_w * recency_w
        sentiment = max(-1.0, min(1.0, event.sentiment_score))
        return _EventContribution(sentiment_score=sentiment, weight=weight)

    def _recency_weight(self, published_at: datetime, now: datetime) -> float:
        age_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
        return math.exp(-age_hours * math.log(2) / self._recency_half_life_hours)

    @staticmethod
    def _snapshot_time(snapshot: DailySnapshot) -> datetime:
        ts = snapshot.latest_bar.timestamp
        if ts.tzinfo is None or ts.utcoffset() is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    @staticmethod
    def _is_classified(event: Event) -> bool:
        """Whether the event has actual sentiment provenance.

        Per Codex re-review (2026-05-20): an earlier version of this
        check accepted any non-empty `model_outputs`, but the enricher
        appends `ModelOutputMeta` even when the LLM response failed
        validation (validation_status="rejected" or "unreviewed"). That
        let failed enrichment masquerade as a classified-neutral signal
        — exactly the dilution this filter is meant to prevent.

        Classified now requires EITHER (a) an explicitly non-default
        sentiment from a normalizer (label!=neutral OR score!=0.0), OR
        (b) at least one `ModelOutputMeta` whose validation_status is
        `auto_passed` or `human_reviewed`. Rejected and unreviewed
        outputs are treated as missing data.
        """
        # Explicit non-default sentiment from any source counts.
        if event.sentiment != "neutral" or event.sentiment_score != 0.0:
            return True
        # Otherwise require a successfully validated model output.
        return any(
            meta.validation_status in {"auto_passed", "human_reviewed"}
            for meta in event.model_outputs
        )

    @staticmethod
    def _relevance(event: Event, ticker: str) -> float | None:
        """Returns event relevance to the trading ticker, or None to skip."""
        ticker = ticker.upper()
        if "macro" in event.asset_scope or "index" in event.asset_scope:
            return 1.0
        if ticker in {t.upper() for t in event.index_exposure}:
            return 0.8
        for entity in event.entities:
            if entity.ticker and entity.ticker.upper() == ticker:
                return 0.6
        return None

    @staticmethod
    def _trend_up(snapshot: DailySnapshot) -> bool | None:
        if snapshot.sma_200 is None:
            return None
        return snapshot.latest_bar.close > snapshot.sma_200

    def _decision_from_aggregate(
        self,
        aggregate: float,
        trend_up: bool | None,
        n_events: int,
        unclassified_skipped: int = 0,
    ) -> Decision:
        skip_note = (
            f"; {unclassified_skipped} unclassified events skipped"
            if unclassified_skipped
            else ""
        )
        base_reason = (
            f"aggregate_sentiment={aggregate:+.3f} over {n_events} relevant events"
            f" (thresholds buy={self._buy_threshold:+.2f} sell={self._sell_threshold:+.2f})"
            f"{skip_note}"
        )

        if aggregate >= self._buy_threshold:
            if trend_up is True:
                return Decision(
                    action="BUY",
                    target_pct=1.0,
                    confidence=0.7,
                    reasoning=f"{base_reason}; trend up (px>SMA200) -> full long",
                )
            if trend_up is False:
                return Decision(
                    action="BUY",
                    target_pct=0.5,
                    confidence=0.4,
                    reasoning=f"{base_reason}; trend down (px<SMA200) -> half exposure",
                )
            return Decision(
                action="BUY",
                target_pct=0.5,
                confidence=0.4,
                reasoning=f"{base_reason}; trend unknown -> half exposure",
            )

        if aggregate <= self._sell_threshold:
            return Decision(
                action="SELL",
                target_pct=0.0,
                confidence=0.6,
                reasoning=f"{base_reason}; bearish -> flat",
            )

        return Decision(
            action="HOLD",
            target_pct=0.5,
            confidence=0.4,
            reasoning=f"{base_reason}; within neutral band",
        )


def sentiment_momentum_conservative(
    *, store: Store, name: str = "SentimentMomentumConservative"
) -> SentimentMomentumBrain:
    """Conservative dial: tight 24h lookback, fast decay, high thresholds,
    reject sources with credibility < 0.7."""
    return SentimentMomentumBrain(
        store=store,
        lookback_hours=24,
        recency_half_life_hours=4.0,
        buy_threshold=0.30,
        sell_threshold=-0.30,
        min_events_for_signal=5,
        credibility_floor=0.7,
        name=name,
    )


def sentiment_momentum_aggressive(
    *, store: Store, name: str = "SentimentMomentumAggressive"
) -> SentimentMomentumBrain:
    """Aggressive dial: wide 72h lookback, slow decay, low thresholds, accept
    all credibility levels."""
    return SentimentMomentumBrain(
        store=store,
        lookback_hours=72,
        recency_half_life_hours=12.0,
        buy_threshold=0.10,
        sell_threshold=-0.10,
        min_events_for_signal=2,
        credibility_floor=0.0,
        name=name,
    )
