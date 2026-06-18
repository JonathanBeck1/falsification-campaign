from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trader.normalization.models import Event
from trader.research.event_candidates import EventCandidate, score_events
from trader.research.event_retrieval import RetrievalHit, retrieve_relevant_events
from trader.storage.store import Store


@dataclass(frozen=True)
class CandidateContext:
    candidate: EventCandidate
    similar_events: list[RetrievalHit]


def build_candidate_contexts(
    *,
    store: Store,
    events: list[Event],
    as_of: datetime,
    candidate_limit: int = 10,
    hits_per_candidate: int = 3,
    min_candidates: int = 30,
    log_retrieval: bool = False,
) -> list[CandidateContext]:
    eligible = [
        event
        for event in events
        if event.observed_at < as_of and event.classified_at is not None and event.classified_at < as_of
    ]
    events_by_id = {event.event_id: event for event in eligible}
    candidates = score_events(eligible)[:candidate_limit]
    contexts: list[CandidateContext] = []
    for candidate in candidates:
        query = events_by_id.get(candidate.event_id)
        if query is None:
            continue
        hits = retrieve_relevant_events(
            store=store,
            query=query,
            as_of=as_of,
            k=hits_per_candidate,
            min_candidates=min_candidates,
            log_retrieval=log_retrieval,
        )
        contexts.append(CandidateContext(candidate=candidate, similar_events=hits))
    return contexts


def format_candidate_context_report(
    contexts: list[CandidateContext],
    *,
    as_of: datetime,
    title: str = "Candidate Context",
) -> str:
    lines = [
        f"# {title}",
        "",
        "This research-only context report is not a trading signal and does not place orders.",
        "",
        f"- As of: `{as_of.isoformat()}`",
        f"- Candidates: {len(contexts)}",
        "",
    ]
    if not contexts:
        lines.append("No candidates met the enrichment and point-in-time filters.")
        lines.append("")
        return "\n".join(lines)

    for context in contexts:
        candidate = context.candidate
        lines.extend(
            [
                f"## `{candidate.event_id}` {candidate.ticker} {candidate.direction} {candidate.score:+.2f}",
                "",
                f"- Event type: `{candidate.event_type}`",
                f"- Urgency: `{candidate.urgency}`",
                f"- Title: {candidate.title}",
                "",
                "| Rank | Score | Event ID | Published | Source | Type | Title |",
                "|---:|---:|---|---|---|---|---|",
            ]
        )
        if context.similar_events:
            for hit in context.similar_events:
                event = hit.event
                title_text = event.title.replace("|", "\\|")
                lines.append(
                    f"| {hit.rank} | {hit.final_score:.3f} | `{event.event_id}` | "
                    f"{event.published_at.isoformat()} | {event.source} | {event.event_type} | {title_text} |"
                )
        else:
            lines.append("| - | - | - | - | - | - | No similar events met the cold-start guard. |")
        lines.append("")
    return "\n".join(lines)
