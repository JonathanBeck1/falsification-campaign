from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Entity, Event, ModelOutputMeta
from trader.research.candidate_context_report import build_candidate_contexts, format_candidate_context_report
from trader.storage.store import Store


def _raw(event_id: str, *, sentiment_score: float = 0.55) -> str:
    return (
        '{"schema_version":"v1","prompt_template_version":"tmpl-v1",'
        f'"event_id":"{event_id}",'
        '"sentiment_label":"positive",'
        f'"sentiment_score":{sentiment_score},'
        '"urgency":"high","novelty_score":0.7,"event_type":"guidance_raise",'
        '"key_claims":[{"text":"Apple raised guidance.",'
        '"quote":"Apple raised guidance","from_field":"summary"}],'
        '"tickers_affected":["AAPL"],'
        '"is_actionable":true,'
        '"confidence":0.8,"abstain_reason":null}'
    )


def _event(event_id: str, *, title: str, published_at: datetime, enriched: bool = False) -> Event:
    event = Event(
        event_id=event_id,
        source="demo_news",
        title=title,
        summary=title,
        published_at=published_at,
        observed_at=published_at,
        ingested_at=published_at,
        classified_at=published_at,
        entities=[Entity(name="Apple Inc.", ticker="AAPL", confidence=0.95, role="primary")],
        asset_scope=["single_name"],
        event_type="guidance_raise",
        sentiment="positive",
        sentiment_score=0.4,
        urgency="high",
        novelty_score=0.7,
        source_credibility=0.7,
    )
    if enriched:
        event.model_outputs.append(
            ModelOutputMeta(
                classifier=ENRICHER_CLASSIFIER,
                prompt_version=PROMPT_TEMPLATE_VERSION,
                raw_output=_raw(event_id),
                validation_status="auto_passed",
                created_at=published_at,
            )
        )
    return event


def test_build_candidate_contexts_links_scored_candidate_to_similar_past_event(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event("evt_query", title="Apple raises services guidance", published_at=as_of - timedelta(minutes=5), enriched=True)
    prior = _event("evt_prior", title="Apple lifts services guidance", published_at=as_of - timedelta(days=10))
    other = _event("evt_other", title="Oil inventories pressure energy stocks", published_at=as_of - timedelta(days=1))
    for event in [query, prior, other]:
        store.save_news_event(event)

    contexts = build_candidate_contexts(
        store=store,
        events=store.get_news_events_parsed(),
        as_of=as_of,
        candidate_limit=3,
        hits_per_candidate=1,
        min_candidates=1,
    )

    assert len(contexts) == 1
    assert contexts[0].candidate.event_id == "evt_query"
    assert [hit.event.event_id for hit in contexts[0].similar_events] == ["evt_prior"]


def test_format_candidate_context_report_includes_candidate_and_similar_events(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event("evt_query", title="Apple raises services guidance", published_at=as_of - timedelta(minutes=5), enriched=True)
    prior = _event("evt_prior", title="Apple lifts services guidance", published_at=as_of - timedelta(days=10))
    for event in [query, prior]:
        store.save_news_event(event)
    contexts = build_candidate_contexts(
        store=store,
        events=store.get_news_events_parsed(),
        as_of=as_of,
        candidate_limit=3,
        hits_per_candidate=1,
        min_candidates=1,
    )

    md = format_candidate_context_report(contexts, as_of=as_of)

    assert "# Candidate Context" in md
    assert "research-only context" in md
    assert "evt_query" in md
    assert "evt_prior" in md
    assert "Apple lifts services guidance" in md
