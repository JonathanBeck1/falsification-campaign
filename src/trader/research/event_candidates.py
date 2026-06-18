from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from trader.enrichment.artifacts import latest_enrichment_artifact
from trader.normalization.models import Event

Direction = Literal["bullish", "bearish", "neutral"]


@dataclass(frozen=True)
class EventCandidate:
    event_id: str
    published_at: datetime
    source: str
    title: str
    ticker: str
    direction: Direction
    score: float
    confidence: float
    is_actionable: bool
    event_type: str
    urgency: str
    reasons: list[str] = field(default_factory=list)
    key_claims: list[str] = field(default_factory=list)


def score_event_candidate(event: Event) -> EventCandidate | None:
    artifact = latest_enrichment_artifact(event)
    if artifact is None or artifact.status not in {"auto_passed", "human_reviewed"}:
        return None

    direction = _direction(artifact.sentiment_score)
    sign = -1.0 if direction == "bearish" else 1.0
    magnitude = 0.0 if direction == "neutral" else abs(artifact.sentiment_score) * 55.0
    reasons = [f"sentiment={artifact.sentiment_score:+.2f}"]

    if artifact.is_actionable:
        magnitude += 12.0
        reasons.append("actionable")
    if artifact.urgency in {"high", "breaking"}:
        magnitude += 10.0
        reasons.append(f"urgency={artifact.urgency}")
    if artifact.novelty_score >= 0.65:
        magnitude += 8.0
        reasons.append(f"novelty={artifact.novelty_score:.2f}")
    if artifact.confidence < 0.4:
        magnitude *= 0.4
        reasons.append(f"low_confidence={artifact.confidence:.2f}")

    score = 0.0 if direction == "neutral" else sign * min(100.0, magnitude)
    return EventCandidate(
        event_id=event.event_id,
        published_at=event.published_at,
        source=event.source,
        title=event.title,
        ticker=_primary_ticker(event, artifact.tickers_affected),
        direction=direction,
        score=round(score, 2),
        confidence=artifact.confidence,
        is_actionable=artifact.is_actionable,
        event_type=artifact.event_type,
        urgency=artifact.urgency,
        reasons=reasons,
        key_claims=artifact.key_claims,
    )


def score_events(events: list[Event]) -> list[EventCandidate]:
    candidates = [candidate for event in events if (candidate := score_event_candidate(event)) is not None]
    return sorted(candidates, key=lambda candidate: abs(candidate.score), reverse=True)


def _direction(sentiment_score: float) -> Direction:
    if sentiment_score >= 0.15:
        return "bullish"
    if sentiment_score <= -0.15:
        return "bearish"
    return "neutral"


def _primary_ticker(event: Event, tickers_affected: list[str]) -> str:
    if tickers_affected:
        return tickers_affected[0]
    for entity in event.entities:
        if entity.ticker:
            return entity.ticker.upper()
    if event.index_exposure:
        return event.index_exposure[0].upper()
    return "UNKNOWN"
