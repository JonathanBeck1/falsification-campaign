from __future__ import annotations

from typing import Literal

from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Event

ReviewFilter = Literal["all", "enriched", "rejected", "missing"]


def latest_enricher_status(event: Event) -> str:
    matches = [
        meta
        for meta in event.model_outputs
        if meta.classifier == ENRICHER_CLASSIFIER and meta.prompt_version == PROMPT_TEMPLATE_VERSION
    ]
    if not matches:
        return "missing"
    return matches[-1].validation_status


def enrichment_bucket(event: Event) -> str:
    status = latest_enricher_status(event)
    if status in {"auto_passed", "human_reviewed"}:
        return "enriched"
    if status == "rejected":
        return "rejected"
    return "missing"


def filter_events_for_review(events: list[Event], *, only: ReviewFilter = "all") -> list[Event]:
    if only == "all":
        return events
    return [event for event in events if enrichment_bucket(event) == only]


def format_review_markdown(events: list[Event]) -> str:
    lines = [
        "# Event Enrichment Review",
        "",
        "| event_id | published_at | source | type | sentiment | urgency | status | title |",
        "|---|---:|---|---|---:|---|---|---|",
    ]
    for event in events:
        title = event.title.replace("|", "\\|")
        lines.append(
            f"| {event.event_id} | {event.published_at.isoformat()} | {event.source} | "
            f"{event.event_type} | {event.sentiment_score:.2f} | {event.urgency} | "
            f"{latest_enricher_status(event)} | {title} |"
        )
    return "\n".join(lines) + "\n"
