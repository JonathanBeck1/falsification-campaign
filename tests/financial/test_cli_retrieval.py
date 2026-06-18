from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from trader.cli import main
from trader.enrichment.seed import seed_demo_events
from trader.normalization.models import Entity, Event
from trader.research.event_retrieval import retrieve_relevant_events
from trader.storage.store import Store


def _event(event_id: str, *, title: str, published_at: datetime) -> Event:
    return Event(
        event_id=event_id,
        source="demo_news",
        title=title,
        summary=title,
        published_at=published_at,
        observed_at=published_at,
        ingested_at=published_at,
        classified_at=published_at,
        entities=[Entity(name="Apple Inc.", ticker="AAPL", confidence=0.9, role="primary")],
        asset_scope=["single_name"],
        event_type="guidance_raise",
        sentiment="positive",
        sentiment_score=0.45,
        urgency="high",
        novelty_score=0.6,
        source_credibility=0.7,
    )


def test_cli_similar_events_writes_retrieval_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "similar-events.md"
    store = Store(db_path)
    as_of = datetime(2026, 5, 20, 15, 0, tzinfo=UTC)
    query = _event("evt_query", title="Apple raises services guidance", published_at=as_of)
    match = _event("evt_match", title="Apple raises guidance after services growth", published_at=as_of - timedelta(days=3))
    other = _event("evt_other", title="Oil prices decline after inventory report", published_at=as_of - timedelta(days=1))
    for event in [query, match, other]:
        store.save_news_event(event)
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    rc = main(
        [
            "similar-events",
            "--event-id",
            "evt_query",
            "--as-of",
            as_of.isoformat(),
            "--k",
            "2",
            "--min-candidates",
            "1",
            "--output",
            str(output_path),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Similar-events report written" in out
    md = output_path.read_text()
    assert "# Similar Events" in md
    assert "point-in-time retrieval" in md
    assert "evt_match" in md
    assert "evt_query" not in md


def test_demo_seed_contains_meaningful_apple_retrieval_history(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    seed_demo_events(store, limit=6)
    query = store.get_news_event_parsed("evt_demo_aapl_guidance")
    assert query is not None

    hits = retrieve_relevant_events(
        store=store,
        query=query,
        as_of=datetime(2026, 5, 20, 14, 0, tzinfo=UTC),
        k=1,
        min_candidates=1,
        log_retrieval=False,
    )

    assert [hit.event.event_id for hit in hits] == ["evt_demo_aapl_prior_services"]
    assert hits[0].sub_scores["relevance"] > 0


def test_cli_candidate_context_writes_context_report(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "candidate-context.md"
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    main(["seed-events", "--demo", "--limit", "6"])
    main(["enrich-events", "--source", "demo_news", "--limit", "6", "--mock-llm"])
    rc = main(
        [
            "candidate-context",
            "--source",
            "demo_news",
            "--as-of",
            "2026-05-20T14:00:00+00:00",
            "--candidate-limit",
            "6",
            "--hits-per-candidate",
            "2",
            "--min-candidates",
            "1",
            "--output",
            str(output_path),
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Candidate-context report written" in out
    md = output_path.read_text()
    assert "# Candidate Context" in md
    assert "evt_demo_aapl_guidance" in md
    assert "evt_demo_aapl_prior_services" in md
