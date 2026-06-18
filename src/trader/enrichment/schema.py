from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from trader.normalization.models import Event, EventType, SentimentLabel, Urgency

SCHEMA_VERSION = "v1"
PROMPT_TEMPLATE_VERSION = "tmpl-v1"
ENRICHER_CLASSIFIER = "event-enricher-v1"
MARKET_INDEX_TICKERS = frozenset({"SPY", "QQQ", "DIA", "IWM"})


class KeyClaim(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=500)
    from_field: Literal["title", "summary"]


class EnrichmentV1(BaseModel):
    schema_version: Literal["v1"]
    prompt_template_version: Literal["tmpl-v1"]
    event_id: str
    sentiment_label: SentimentLabel
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    urgency: Urgency
    novelty_score: float = Field(ge=0.0, le=1.0)
    event_type: EventType
    key_claims: list[KeyClaim] = Field(min_length=1, max_length=3)
    tickers_affected: list[str] = Field(default_factory=list, max_length=12)
    is_actionable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    abstain_reason: str | None = None

    @model_validator(mode="after")
    def _sentiment_score_matches_label(self) -> EnrichmentV1:
        if self.sentiment_label == "positive" and self.sentiment_score < 0:
            raise ValueError("positive sentiment requires non-negative sentiment_score")
        if self.sentiment_label == "negative" and self.sentiment_score > 0:
            raise ValueError("negative sentiment requires non-positive sentiment_score")
        if self.sentiment_label == "neutral" and abs(self.sentiment_score) > 0.1:
            raise ValueError("neutral sentiment_score must be between -0.1 and 0.1")
        return self


@dataclass(frozen=True)
class EnrichmentValidation:
    enrichment: EnrichmentV1
    validation_status: Literal["auto_passed", "rejected"]
    reason: str = ""


def _article_text_for_claim(event: Event, from_field: str) -> str:
    return event.title if from_field == "title" else event.summary


def _allowed_tickers(event: Event) -> set[str]:
    from_entities = {
        entity.ticker.upper()
        for entity in event.entities
        if entity.ticker is not None and entity.ticker.strip()
    }
    from_index_exposure = {ticker.upper() for ticker in event.index_exposure}
    return set(MARKET_INDEX_TICKERS) | from_entities | from_index_exposure


def _quote_supported(event: Event, claim: KeyClaim) -> bool:
    text = _article_text_for_claim(event, claim.from_field).lower()
    return claim.quote.lower() in text


def validate_enrichment_for_event(enrichment: EnrichmentV1, event: Event) -> EnrichmentValidation:
    if enrichment.event_id != event.event_id:
        return EnrichmentValidation(enrichment, "rejected", "event_id mismatch")

    requested_tickers = {ticker.upper() for ticker in enrichment.tickers_affected}
    disallowed = sorted(requested_tickers - _allowed_tickers(event))
    if disallowed:
        return EnrichmentValidation(enrichment, "rejected", f"disallowed tickers: {','.join(disallowed)}")

    supported_claims = [claim for claim in enrichment.key_claims if _quote_supported(event, claim)]
    if not supported_claims:
        return EnrichmentValidation(enrichment, "rejected", "no supported key_claims")

    if len(supported_claims) != len(enrichment.key_claims):
        enrichment = enrichment.model_copy(update={"key_claims": supported_claims})

    if enrichment.abstain_reason:
        return EnrichmentValidation(enrichment, "rejected", f"model abstained: {enrichment.abstain_reason}")

    return EnrichmentValidation(enrichment, "auto_passed")
