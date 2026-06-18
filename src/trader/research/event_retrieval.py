from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from trader.normalization.models import Event
from trader.storage.store import Store

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")
_STOPWORDS = {
    "a",
    "after",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "said",
    "the",
    "to",
    "with",
}

_URGENCY_WEIGHT = {"low": 0.2, "normal": 0.4, "high": 0.7, "breaking": 1.0}
_EVENT_TYPE_PRIOR = {
    "fed_commentary": 1.0,
    "guidance_raise": 1.0,
    "guidance_lower": 1.0,
    "earnings_surprise": 0.9,
    "mna": 0.9,
    "regulatory_action": 0.9,
    "macro_surprise": 0.85,
    "analyst_upgrade": 0.6,
    "analyst_downgrade": 0.6,
    "unusual_social_velocity": 0.5,
    "other": 0.3,
}


@dataclass(frozen=True)
class RetrievalWeights:
    recency: float = 1.0
    importance: float = 1.0
    relevance: float = 2.0


@dataclass(frozen=True)
class RetrievalFilters:
    event_types: list[str] | None = None
    sources: list[str] | None = None


@dataclass(frozen=True)
class RetrievalHit:
    event: Event
    final_score: float
    sub_scores: dict[str, float]
    sub_scores_raw: dict[str, float]
    rank: int


DEFAULT_RETRIEVAL_WEIGHTS = RetrievalWeights()


def format_retrieval_report(
    hits: list[RetrievalHit],
    *,
    query: Event | str,
    as_of: datetime,
    title: str = "Similar Events",
) -> str:
    query_text = _query_text(query).replace("|", "\\|")
    lines = [
        f"# {title}",
        "",
        "Research-only point-in-time retrieval. This is not a trading signal and does not place orders.",
        "",
        f"- As of: `{as_of.isoformat()}`",
        f"- Query: {query_text}",
        f"- Hits: {len(hits)}",
        "",
        "| Rank | Score | Event ID | Published | Source | Type | Title | Components |",
        "|---:|---:|---|---|---|---|---|---|",
    ]
    for hit in hits:
        event = hit.event
        title_text = event.title.replace("|", "\\|")
        components = ", ".join(
            f"{name}={value:.2f}" for name, value in sorted(hit.sub_scores.items())
        )
        lines.append(
            f"| {hit.rank} | {hit.final_score:.3f} | `{event.event_id}` | "
            f"{event.published_at.isoformat()} | {event.source} | {event.event_type} | {title_text} | {components} |"
        )
    if not hits:
        lines.append("| - | - | - | - | - | - | No similar events met the filters/cold-start guard. | - |")
    lines.append("")
    return "\n".join(lines)


def retrieve_relevant_events(
    *,
    store: Store,
    query: Event | str,
    as_of: datetime,
    k: int = 20,
    min_candidates: int = 30,
    decay_half_life_hours: float = 24 * 120,
    weights: RetrievalWeights = DEFAULT_RETRIEVAL_WEIGHTS,
    filters: RetrievalFilters | None = None,
    log_retrieval: bool = True,
) -> list[RetrievalHit]:
    if k <= 0:
        return []
    candidates = _candidate_events(store, query=query, as_of=as_of, filters=filters)
    if len(candidates) < min_candidates:
        return []

    query_text = _query_text(query)
    query_tokens = _tokens(query_text)
    docs = [_tokens(_event_text(event)) for event in candidates]
    relevance_scores = _bm25_scores(query_tokens, docs)
    latest_retrievals = store.latest_event_retrievals_before(
        [event.event_id for event in candidates],
        before=as_of,
    )

    raw_rows: list[tuple[Event, dict[str, float]]] = []
    for event, relevance in zip(candidates, relevance_scores, strict=True):
        raw_rows.append(
            (
                event,
                {
                    "recency": _recency_score(event, as_of=as_of, latest_retrievals=latest_retrievals, half_life_hours=decay_half_life_hours),
                    "importance": _importance_score(event),
                    "relevance": relevance,
                },
            )
        )

    normalized = _normalize_components([raw for _, raw in raw_rows])
    hits = [
        RetrievalHit(
            event=event,
            final_score=round(
                weights.recency * scores["recency"]
                + weights.importance * scores["importance"]
                + weights.relevance * scores["relevance"],
                6,
            ),
            sub_scores=scores,
            sub_scores_raw=raw,
            rank=0,
        )
        for (event, raw), scores in zip(raw_rows, normalized, strict=True)
    ]
    hits = sorted(
        hits,
        key=lambda hit: (
            hit.final_score,
            hit.sub_scores["relevance"],
            hit.sub_scores["importance"],
            hit.event.published_at,
            hit.event.event_id,
        ),
        reverse=True,
    )[:k]
    ranked = [
        RetrievalHit(
            event=hit.event,
            final_score=hit.final_score,
            sub_scores=hit.sub_scores,
            sub_scores_raw=hit.sub_scores_raw,
            rank=index,
        )
        for index, hit in enumerate(hits, start=1)
    ]
    if log_retrieval:
        query_hash = _query_hash(query_text)
        retrieved_at = datetime.now(UTC)
        for hit in ranked:
            store.record_event_retrieval(hit.event.event_id, retrieved_at=retrieved_at, query_hash=query_hash)
    return ranked


def _candidate_events(
    store: Store,
    *,
    query: Event | str,
    as_of: datetime,
    filters: RetrievalFilters | None,
) -> list[Event]:
    query_event_id = query.event_id if isinstance(query, Event) else None
    out: list[Event] = []
    for event in store.get_news_events_parsed(until=as_of, limit=100_000):
        if event.event_id == query_event_id:
            continue
        if event.observed_at >= as_of:
            continue
        if event.classified_at is None or event.classified_at >= as_of:
            continue
        if filters and filters.event_types and event.event_type not in filters.event_types:
            continue
        if filters and filters.sources and event.source not in filters.sources:
            continue
        out.append(event)
    return out


def _event_text(event: Event) -> str:
    return f"{event.title} {event.summary}".strip()


def _query_text(query: Event | str) -> str:
    if isinstance(query, Event):
        return _event_text(query)
    return query


def _query_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS]


def _bm25_scores(query_tokens: list[str], docs: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    if not query_tokens or not docs:
        return [0.0 for _ in docs]
    doc_freq: Counter[str] = Counter()
    for doc in docs:
        doc_freq.update(set(doc))
    avg_len = sum(len(doc) for doc in docs) / len(docs) if docs else 0.0
    if avg_len == 0:
        return [0.0 for _ in docs]

    query_counts = Counter(query_tokens)
    scores: list[float] = []
    for doc in docs:
        tf = Counter(doc)
        doc_len = len(doc)
        score = 0.0
        for token in query_counts:
            if token not in tf:
                continue
            idf = math.log(1 + (len(docs) - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
            numerator = tf[token] * (k1 + 1)
            denominator = tf[token] + k1 * (1 - b + b * doc_len / avg_len)
            score += idf * numerator / denominator
        scores.append(score)
    return scores


def _recency_score(
    event: Event,
    *,
    as_of: datetime,
    latest_retrievals: dict[str, datetime],
    half_life_hours: float,
) -> float:
    reference = latest_retrievals.get(event.event_id, event.published_at)
    elapsed_hours = max((as_of - reference).total_seconds() / 3600, 0.0)
    if half_life_hours <= 0:
        return 0.0
    return math.exp(-math.log(2) * elapsed_hours / half_life_hours)


def _importance_score(event: Event) -> float:
    urgency = _URGENCY_WEIGHT.get(event.urgency, 0.4)
    narrative_intensity = abs(event.sentiment_score) * urgency
    event_type_prior = _EVENT_TYPE_PRIOR.get(event.event_type, _EVENT_TYPE_PRIOR["other"])
    return _clamp_0_1(
        0.35 * urgency
        + 0.20 * event.source_credibility
        + 0.15 * event.novelty_score
        + 0.15 * narrative_intensity
        + 0.15 * event_type_prior
    )


def _normalize_components(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    if not rows:
        return []
    keys = rows[0].keys()
    ranges: dict[str, tuple[float, float]] = {
        key: (min(row[key] for row in rows), max(row[key] for row in rows)) for key in keys
    }
    out: list[dict[str, float]] = []
    for row in rows:
        normalized: dict[str, float] = {}
        for key, value in row.items():
            low, high = ranges[key]
            normalized[key] = 0.0 if high == low else round((value - low) / (high - low), 6)
        out.append(normalized)
    return out


def _clamp_0_1(value: float) -> float:
    return max(0.0, min(1.0, value))
