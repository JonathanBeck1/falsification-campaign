from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from trader.enrichment.prompts import build_enrichment_messages
from trader.enrichment.schema import (
    ENRICHER_CLASSIFIER,
    PROMPT_TEMPLATE_VERSION,
    EnrichmentV1,
    validate_enrichment_for_event,
)
from trader.llm.client import LLMClient, LLMResponse
from trader.normalization.models import Event, ModelOutputMeta
from trader.storage.store import Store


class CompleteLLM(Protocol):
    def complete(self, **kwargs) -> LLMResponse: ...


@dataclass(frozen=True)
class EnrichmentSummary:
    seen: int = 0
    enriched: int = 0
    rejected: int = 0
    skipped_budget: int = 0
    dry_run: bool = False


class EventEnricher:
    def __init__(self, *, store: Store, llm: CompleteLLM | None = None, daily_budget_usd: float = 1.0) -> None:
        self.store = store
        self.llm = llm or LLMClient()
        self.daily_budget_usd = daily_budget_usd

    def run(
        self,
        *,
        limit: int = 25,
        since: datetime | None = None,
        source: str | None = None,
        dry_run: bool = False,
    ) -> EnrichmentSummary:
        if self.store.llm_cost_today() >= self.daily_budget_usd:
            return EnrichmentSummary(skipped_budget=1, dry_run=dry_run)

        candidates = self.store.get_events_needing_enrichment(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            since=since,
            source=source,
            limit=limit,
        )

        seen = enriched = rejected = 0
        for event in candidates:
            if self.store.llm_cost_today() >= self.daily_budget_usd:
                return EnrichmentSummary(
                    seen=seen,
                    enriched=enriched,
                    rejected=rejected,
                    skipped_budget=1,
                    dry_run=dry_run,
                )

            seen += 1
            system, user = build_enrichment_messages(event)
            response = self.llm.complete(
                system=system,
                user=user,
                response_format_json=True,
                max_tokens=700,
                temperature=0.0,
            )
            if not dry_run:
                self.store.record_llm_call(
                    decision_id=None,
                    brain="EventEnricher",
                    model=response.model,
                    prompt_hash=response.prompt_hash,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cached_tokens=response.cached_tokens,
                    cost_usd=response.cost_usd,
                    latency_ms=response.latency_ms,
                )

            updated, ok = self._apply_response(event, response)
            if ok:
                enriched += 1
            else:
                rejected += 1
            if not dry_run:
                self.store.update_news_event_enrichment(updated)

        return EnrichmentSummary(seen=seen, enriched=enriched, rejected=rejected, skipped_budget=0, dry_run=dry_run)

    def _apply_response(self, event: Event, response: LLMResponse) -> tuple[Event, bool]:
        now = datetime.now(UTC)
        try:
            payload = response.parsed if response.parsed is not None else json.loads(response.content)
            enrichment = EnrichmentV1.model_validate(payload)
            validation = validate_enrichment_for_event(enrichment, event)
        except (json.JSONDecodeError, ValidationError, ValueError):
            meta = ModelOutputMeta(
                classifier=ENRICHER_CLASSIFIER,
                prompt_version=PROMPT_TEMPLATE_VERSION,
                raw_output=response.content,
                validation_status="rejected",
                created_at=now,
            )
            return event.model_copy(update={"model_outputs": [*event.model_outputs, meta]}), False

        meta = ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output=response.content,
            validation_status=validation.validation_status,
            created_at=now,
        )
        model_outputs = [*event.model_outputs, meta]
        if validation.validation_status == "rejected":
            return event.model_copy(update={"model_outputs": model_outputs}), False

        enrichment = validation.enrichment
        updated = event.model_copy(
            update={
                "event_type": enrichment.event_type,
                "sentiment": enrichment.sentiment_label,
                "sentiment_score": 0.0 if enrichment.confidence < 0.4 else enrichment.sentiment_score,
                "urgency": "normal" if enrichment.confidence < 0.4 else enrichment.urgency,
                "novelty_score": enrichment.novelty_score,
                "model_outputs": model_outputs,
            }
        )
        return updated, True


def enrich_events(
    *,
    store: Store,
    llm: CompleteLLM | None = None,
    limit: int = 25,
    since: datetime | None = None,
    source: str | None = None,
    dry_run: bool = False,
    daily_budget_usd: float = 1.0,
) -> EnrichmentSummary:
    return EventEnricher(store=store, llm=llm, daily_budget_usd=daily_budget_usd).run(
        limit=limit,
        since=since,
        source=source,
        dry_run=dry_run,
    )
