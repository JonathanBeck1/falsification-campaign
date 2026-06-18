from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from trader.cli import main
from trader.enrichment.review import format_review_markdown
from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Event, ModelOutputMeta
from trader.storage.store import Store


def _event() -> Event:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    event = Event(
        event_id="evt_review",
        source="marketwatch.com",
        title="Fed comments move SPY",
        summary="Powell said the Fed will be patient on interest rates.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        event_type="fed_commentary",
        sentiment="negative",
        sentiment_score=-0.4,
        urgency="high",
    )
    event.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output='{"ok": true}',
            validation_status="auto_passed",
            created_at=now,
        )
    )
    return event


def test_review_markdown_contains_event_fields():
    md = format_review_markdown([_event()])
    assert "# Event Enrichment Review" in md
    assert "evt_review" in md
    assert "Fed comments move SPY" in md
    assert "auto_passed" in md


def test_cli_enrich_events_dry_run(monkeypatch, capsys):
    calls = {}

    def fake_enrich_events(**kwargs):
        calls.update(kwargs)
        return type("Summary", (), {"seen": 2, "enriched": 1, "rejected": 1, "skipped_budget": 0, "dry_run": True})()

    monkeypatch.setattr("trader.cli.enrich_events", fake_enrich_events)

    rc = main(["enrich-events", "--limit", "2", "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert calls["limit"] == 2
    assert calls["dry_run"] is True
    assert "seen=2 enriched=1 rejected=1 skipped_budget=0 dry_run=True" in out


def test_cli_enrich_events_mock_llm_persists_without_api(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    event = _event()
    event.sentiment = "neutral"
    event.sentiment_score = 0.0
    event.model_outputs = []
    store.save_news_event(event)
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    rc = main(["enrich-events", "--limit", "1", "--mock-llm"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "seen=1 enriched=1 rejected=0 skipped_budget=0 dry_run=False" in out
    parsed = store.get_news_events_parsed()
    assert parsed[0].model_outputs[0].classifier == ENRICHER_CLASSIFIER
    assert parsed[0].model_outputs[0].validation_status == "auto_passed"


def test_cli_seed_events_creates_demo_rows(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "trader.sqlite"
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    rc = main(["seed-events", "--demo", "--limit", "3"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Seeded demo events: 3" in out
    store = Store(db_path)
    events = store.get_news_events_parsed()
    assert len(events) == 3
    assert {event.source for event in events} == {"demo_news"}


def test_cli_enrichment_status_counts_versions(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    missing = _event()
    missing.event_id = "evt_missing"
    missing.model_outputs = []
    enriched = _event()
    enriched.event_id = "evt_enriched"
    rejected = _event()
    rejected.event_id = "evt_rejected"
    rejected.model_outputs[0] = rejected.model_outputs[0].model_copy(update={"validation_status": "rejected"})
    for event in [missing, enriched, rejected]:
        store.save_news_event(event)
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    rc = main(["enrichment-status"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "total=3" in out
    assert "enriched=1" in out
    assert "rejected=1" in out
    assert "missing=1" in out


def test_cli_review_events_filters_by_status(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "review.md"
    store = Store(db_path)
    enriched = _event()
    enriched.event_id = "evt_enriched"
    enriched.title = "Enriched event"
    rejected = _event()
    rejected.event_id = "evt_rejected"
    rejected.title = "Rejected event"
    rejected.model_outputs[0] = rejected.model_outputs[0].model_copy(update={"validation_status": "rejected"})
    store.save_news_event(enriched)
    store.save_news_event(rejected)
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    rc = main(["review-events", "--only", "rejected", "--output", str(output_path)])
    capsys.readouterr()

    assert rc == 0
    md = output_path.read_text()
    assert "Rejected event" in md
    assert "Enriched event" not in md


def test_mock_llm_produces_varied_sentiment(monkeypatch, tmp_path):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    main(["seed-events", "--demo", "--limit", "5"])
    main(["enrich-events", "--source", "demo_news", "--limit", "5", "--mock-llm"])

    events = store.get_news_events_parsed(source="demo_news")
    scores = [event.sentiment_score for event in events]
    labels = {event.sentiment for event in events}

    assert any(score > 0 for score in scores)
    assert any(score < 0 for score in scores)
    assert {"positive", "negative"} <= labels


def test_cli_score_events_writes_candidate_report(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "trader.sqlite"
    output_path = tmp_path / "event-candidates.md"
    monkeypatch.setattr(
        "trader.cli.get_settings",
        lambda: SimpleNamespace(sqlite_path=db_path, trader_llm_daily_budget_usd=1.0),
    )

    main(["seed-events", "--demo", "--limit", "5"])
    main(["enrich-events", "--source", "demo_news", "--limit", "5", "--mock-llm"])
    rc = main(["score-events", "--source", "demo_news", "--limit", "5", "--output", str(output_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Candidate report written" in out
    md = output_path.read_text()
    assert "# Event Candidates" in md
    assert "Research-only candidate list" in md
    assert "demo_news" in md
    assert "MSFT" in md
    assert "NVDA" in md
