from __future__ import annotations

from dataclasses import dataclass

from trader.enrichment.review import enrichment_bucket
from trader.normalization.models import Event


@dataclass(frozen=True)
class EnrichmentStatus:
    total: int
    enriched: int
    rejected: int
    missing: int
    llm_cost_today: float


def compute_enrichment_status(events: list[Event], *, llm_cost_today: float = 0.0) -> EnrichmentStatus:
    enriched = rejected = missing = 0
    for event in events:
        bucket = enrichment_bucket(event)
        if bucket == "enriched":
            enriched += 1
        elif bucket == "rejected":
            rejected += 1
        else:
            missing += 1
    return EnrichmentStatus(
        total=len(events),
        enriched=enriched,
        rejected=rejected,
        missing=missing,
        llm_cost_today=llm_cost_today,
    )
