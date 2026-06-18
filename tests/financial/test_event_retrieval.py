from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trader.normalization.models import Entity, Event
from trader.research.event_retrieval import RetrievalFilters, retrieve_relevant_events
from trader.storage.store import Store


def _event(
    event_id: str,
    *,
    title: str,
    summary: str = "",
    published_at: datetime,
    observed_at: datetime | None = None,
    classified_at: datetime | None = None,
    event_type: str = "guidance_raise",
    sentiment_score: float = 0.4,
    urgency: str = "normal",
    source_credibility: float = 0.6,
    novelty_score: float = 0.5,
    source: str = "demo_news",
) -> Event:
    observed = observed_at or published_at
    return Event(
        event_id=event_id,
        source=source,
        title=title,
        summary=summary,
        published_at=published_at,
        observed_at=observed,
        ingested_at=observed,
        classified_at=classified_at or observed,
        entities=[Entity(name="Apple Inc.", ticker="AAPL", confidence=0.9, role="primary")],
        asset_scope=["single_name"],
        event_type=event_type,
        sentiment="positive" if sentiment_score > 0 else "negative",
        sentiment_score=sentiment_score,
        urgency=urgency,
        source_credibility=source_credibility,
        novelty_score=novelty_score,
    )


def test_retrieve_relevant_events_ranks_matching_text_and_logs(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event(
        "evt_query",
        title="Apple raises services guidance",
        summary="Apple lifted guidance after services revenue accelerated.",
        published_at=as_of,
    )
    matching = _event(
        "evt_match",
        title="Apple lifts guidance after services growth",
        summary="Services revenue pushed Apple guidance higher.",
        published_at=as_of - timedelta(days=5),
    )
    unrelated = _event(
        "evt_unrelated",
        title="Oil prices fall after inventory report",
        summary="Crude inventories rose and energy shares traded lower.",
        published_at=as_of - timedelta(days=2),
        event_type="macro_surprise",
    )
    for event in [query, matching, unrelated]:
        store.save_news_event(event)

    hits = retrieve_relevant_events(store=store, query=query, as_of=as_of, k=2, min_candidates=1)

    assert [hit.event.event_id for hit in hits] == ["evt_match", "evt_unrelated"]
    assert hits[0].rank == 1
    assert hits[0].sub_scores["relevance"] > hits[1].sub_scores["relevance"]
    logged = store.latest_event_retrievals_before(["evt_match"], before=datetime.now(UTC) + timedelta(seconds=1))
    assert "evt_match" in logged


def test_retrieve_relevant_events_excludes_future_observed_or_classified_events(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event("evt_query", title="Nvidia launches AI chip", published_at=as_of)
    valid = _event("evt_valid", title="Nvidia launches AI accelerator", published_at=as_of - timedelta(days=3))
    future_observed = _event(
        "evt_future_observed",
        title="Nvidia launches AI chip with huge demand",
        published_at=as_of - timedelta(days=10),
        observed_at=as_of + timedelta(minutes=1),
        classified_at=as_of + timedelta(minutes=1),
    )
    future_classified = _event(
        "evt_future_classified",
        title="Nvidia launches AI chip after customer demand",
        published_at=as_of - timedelta(days=10),
        observed_at=as_of - timedelta(days=9),
        classified_at=as_of + timedelta(minutes=1),
    )
    for event in [query, valid, future_observed, future_classified]:
        store.save_news_event(event)

    hits = retrieve_relevant_events(store=store, query=query, as_of=as_of, k=5, min_candidates=1)

    assert [hit.event.event_id for hit in hits] == ["evt_valid"]


def test_retrieval_log_after_as_of_does_not_freshen_recency(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    old_past_retrieved = _event(
        "evt_old_past",
        title="Fed patience interest rates",
        published_at=as_of - timedelta(days=90),
        event_type="fed_commentary",
    )
    old_future_retrieved = _event(
        "evt_old_future",
        title="Fed patience interest rates",
        published_at=as_of - timedelta(days=90),
        event_type="fed_commentary",
    )
    query = _event("evt_query", title="Fed patience interest rates", published_at=as_of, event_type="fed_commentary")
    for event in [query, old_past_retrieved, old_future_retrieved]:
        store.save_news_event(event)
    store.record_event_retrieval("evt_old_past", retrieved_at=as_of - timedelta(hours=1), query_hash="before")
    store.record_event_retrieval("evt_old_future", retrieved_at=as_of + timedelta(hours=1), query_hash="after")

    hits = retrieve_relevant_events(store=store, query=query, as_of=as_of, k=2, min_candidates=1, log_retrieval=False)

    by_id = {hit.event.event_id: hit for hit in hits}
    assert by_id["evt_old_past"].sub_scores_raw["recency"] > by_id["evt_old_future"].sub_scores_raw["recency"]


def test_retrieve_relevant_events_cold_start_returns_empty_without_logging(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event("evt_query", title="Apple raises guidance", published_at=as_of)
    only_candidate = _event("evt_one", title="Apple lifts guidance", published_at=as_of - timedelta(days=1))
    for event in [query, only_candidate]:
        store.save_news_event(event)

    hits = retrieve_relevant_events(store=store, query=query, as_of=as_of, k=5, min_candidates=2)

    assert hits == []
    assert store.latest_event_retrievals_before(["evt_one"], before=as_of + timedelta(seconds=1)) == {}


def test_retrieve_relevant_events_applies_filters(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event("evt_query", title="Fed rates guidance", published_at=as_of)
    fed = _event(
        "evt_fed",
        title="Fed rates guidance",
        published_at=as_of - timedelta(days=1),
        event_type="fed_commentary",
        source="federalreserve.gov",
    )
    guidance = _event(
        "evt_guidance",
        title="Company guidance rates",
        published_at=as_of - timedelta(days=1),
        event_type="guidance_raise",
        source="demo_news",
    )
    for event in [query, fed, guidance]:
        store.save_news_event(event)

    hits = retrieve_relevant_events(
        store=store,
        query=query,
        as_of=as_of,
        k=5,
        min_candidates=1,
        filters=RetrievalFilters(event_types=["fed_commentary"], sources=["federalreserve.gov"]),
    )

    assert [hit.event.event_id for hit in hits] == ["evt_fed"]
