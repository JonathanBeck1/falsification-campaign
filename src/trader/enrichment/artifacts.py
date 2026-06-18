from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION, EnrichmentV1
from trader.normalization.models import Event, ModelOutputMeta


@dataclass(frozen=True)
class EnrichmentArtifact:
    event_id: str
    status: str
    sentiment_label: str
    sentiment_score: float
    urgency: str
    novelty_score: float
    event_type: str
    tickers_affected: list[str]
    is_actionable: bool
    confidence: float
    abstain_reason: str | None
    key_claims: list[str]


def latest_enrichment_meta(event: Event) -> ModelOutputMeta | None:
    matches = [
        meta
        for meta in event.model_outputs
        if meta.classifier == ENRICHER_CLASSIFIER and meta.prompt_version == PROMPT_TEMPLATE_VERSION
    ]
    if not matches:
        return None
    return max(matches, key=lambda meta: meta.created_at)


def latest_enrichment_artifact(event: Event) -> EnrichmentArtifact | None:
    meta = latest_enrichment_meta(event)
    if meta is None or not meta.raw_output:
        return None
    try:
        payload = json.loads(meta.raw_output)
        enrichment = EnrichmentV1.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return None
    return EnrichmentArtifact(
        event_id=enrichment.event_id,
        status=meta.validation_status,
        sentiment_label=enrichment.sentiment_label,
        sentiment_score=enrichment.sentiment_score,
        urgency=enrichment.urgency,
        novelty_score=enrichment.novelty_score,
        event_type=enrichment.event_type,
        tickers_affected=[ticker.upper() for ticker in enrichment.tickers_affected],
        is_actionable=enrichment.is_actionable,
        confidence=enrichment.confidence,
        abstain_reason=enrichment.abstain_reason,
        key_claims=[claim.text for claim in enrichment.key_claims],
    )
