"""Tests for the Fed RSS -> Event normalizer + news_events storage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trader.normalization.fed import (
    _classify_event_type,
    _classify_urgency,
    fed_news_to_events,
)
from trader.normalization.models import Event
from trader.storage.snapshot import NewsItem
from trader.storage.store import Store
from trader.storage.utc import to_iso_z

# ── urgency / event-type classifiers ─────────────────────────────────────────


def test_classify_urgency_fomc_statement_is_breaking():
    assert _classify_urgency("FOMC Statement on Monetary Policy") == "breaking"


def test_classify_urgency_rate_decision_is_breaking():
    assert _classify_urgency("Federal Reserve Rate Decision Announced") == "breaking"


def test_classify_urgency_press_conference_is_high():
    assert _classify_urgency("Press Conference After FOMC Meeting") == "high"


def test_classify_urgency_routine_release_is_normal():
    assert _classify_urgency("Minutes of the FOMC Meeting") == "normal"


def test_classify_event_type_defaults_to_fed_commentary():
    assert _classify_event_type("Random Fed Title") == "fed_commentary"


# ── normalizer ───────────────────────────────────────────────────────────────


def _make_item(headline: str, summary: str = "", hour: int = 14) -> NewsItem:
    return NewsItem(
        headline=headline,
        summary=summary,
        source="federalreserve.gov",
        published_at=datetime(2026, 5, 18, hour, 0, tzinfo=UTC),
    )


def test_fed_news_to_events_strips_adapter_prefix():
    """The adapter prefixes titles with '[Federal Reserve] '. Normalizer should strip it."""
    items = [_make_item("[Federal Reserve] FOMC Statement on Monetary Policy")]
    events = fed_news_to_events(items)
    assert len(events) == 1
    assert events[0].title == "FOMC Statement on Monetary Policy"


def test_fed_news_to_events_populates_required_fields():
    items = [_make_item("FOMC Statement on Monetary Policy", "The Committee decided to maintain...")]
    events = fed_news_to_events(items)
    e = events[0]
    assert e.source == "federalreserve.gov"
    assert e.event_type == "fed_commentary"
    assert e.urgency == "breaking"
    assert e.asset_scope == ["macro", "index"]
    assert e.index_exposure == ["SPY", "QQQ"]
    assert e.source_credibility >= 0.9
    assert e.event_id.startswith("evt_")
    # Evidence retained from raw summary
    assert len(e.evidence) == 1
    assert "Committee decided" in e.evidence[0].text


def test_fed_news_to_events_empty_input_returns_empty():
    assert fed_news_to_events([]) == []


def test_fed_news_to_events_handles_missing_summary():
    """Some Fed entries have empty summaries; evidence should fall back to title."""
    items = [_make_item("Speech by the Chair")]
    events = fed_news_to_events(items)
    assert events[0].evidence[0].text == "Speech by the Chair"


def test_fed_news_to_events_assigns_unique_ids():
    items = [_make_item("Statement A"), _make_item("Statement B")]
    events = fed_news_to_events(items)
    assert events[0].event_id != events[1].event_id


def test_fed_news_to_events_uses_deterministic_ids_for_same_item():
    item = _make_item("Statement A", "A stable source item.")

    first = fed_news_to_events([item])[0]
    second = fed_news_to_events([item])[0]

    assert first.event_id == second.event_id


# ── store roundtrip ──────────────────────────────────────────────────────────


def test_save_news_event_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    items = [_make_item("FOMC Statement on Monetary Policy", "Body text")]
    events = fed_news_to_events(items)
    store.save_news_event(events[0])

    rows = store.get_news_events()
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "fed_commentary"
    assert row["urgency"] == "breaking"
    assert row["source"] == "federalreserve.gov"
    # JSON columns persist as strings, but should be valid JSON
    import json

    assert json.loads(row["index_exposure_json"]) == ["SPY", "QQQ"]


def test_get_news_events_filters_by_source(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    for item in fed_news_to_events([_make_item("FOMC A")]):
        store.save_news_event(item)
    assert store.count_news_events(source="federalreserve.gov") == 1
    assert store.count_news_events(source="some_other") == 0


def test_get_news_events_filters_by_event_type(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    for item in fed_news_to_events([_make_item("FOMC A")]):
        store.save_news_event(item)
    assert len(store.get_news_events(event_type="fed_commentary")) == 1
    assert len(store.get_news_events(event_type="earnings_surprise")) == 0


def test_save_news_event_updates_mutable_fields_on_duplicate_id(tmp_path: Path):
    """Same event_id updates mutable fields without creating a duplicate row."""
    store = Store(tmp_path / "trader.sqlite")
    first_seen = datetime(2026, 5, 18, 15, 0, tzinfo=UTC)
    refetched_at = first_seen + timedelta(hours=2)
    items = fed_news_to_events([_make_item("Statement A")], observed_at=first_seen)
    events_list = list(items)
    e1 = events_list[0]
    e2 = Event(
        **{
            **e1.model_dump(),
            "title": "Statement A (corrected)",
            "observed_at": refetched_at,
            "ingested_at": refetched_at,
            "sentiment": "positive",
            "sentiment_score": 0.75,
        },
    )
    store.save_news_event(e1)
    store.save_news_event(e2)
    rows = store.get_news_events()
    assert len(rows) == 1
    assert rows[0]["title"] == "Statement A (corrected)"
    assert rows[0]["sentiment"] == "positive"
    assert rows[0]["sentiment_score"] == 0.75


def test_save_news_event_preserves_first_seen_timing_on_reingestion(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    first_seen = datetime(2026, 5, 18, 15, 0, tzinfo=UTC)
    refetched_at = first_seen + timedelta(hours=2)
    e1 = fed_news_to_events([_make_item("Statement A")], observed_at=first_seen)[0]
    e2 = Event(
        **{
            **e1.model_dump(),
            "observed_at": refetched_at,
            "ingested_at": refetched_at,
        },
    )

    store.save_news_event(e1)
    store.save_news_event(e2)

    row = store.get_news_events()[0]
    assert row["observed_at"] == to_iso_z(first_seen)
    assert row["ingested_at"] == to_iso_z(first_seen)
    assert row["last_seen_at"] == to_iso_z(refetched_at)


def test_last_seen_at_is_monotonic_under_enrichment_update(tmp_path: Path):
    """Per Codex re-review (2026-05-20): the enrichment update path
    reconstructs an Event from storage, which carries the ORIGINAL
    observed_at — not the latest sighting. Without the monotonic guard
    on `last_seen_at`, applying that reconstructed Event would *regress*
    last_seen_at back to the first observation. This test pins the
    invariant: last_seen_at only ever moves forward."""
    store = Store(tmp_path / "trader.sqlite")
    first_seen = datetime(2026, 5, 18, 15, 0, tzinfo=UTC)
    refetched_at = first_seen + timedelta(hours=2)

    # Step 1: first ingestion.
    e1 = fed_news_to_events([_make_item("Statement A")], observed_at=first_seen)[0]
    store.save_news_event(e1)

    # Step 2: re-ingestion 2h later — last_seen_at advances.
    e2 = Event(
        **{
            **e1.model_dump(),
            "observed_at": refetched_at,
            "ingested_at": refetched_at,
        },
    )
    store.save_news_event(e2)
    assert store.get_news_events()[0]["last_seen_at"] == to_iso_z(refetched_at)

    # Step 3: enrichment update reconstructs Event from storage. The
    # observed_at on the reconstructed Event is first_seen (the row's
    # frozen first-observation timestamp), NOT refetched_at or
    # enrichment_time. Without the monotonic guard, this would regress
    # last_seen_at back to first_seen.
    e3 = Event(
        **{
            **e1.model_dump(),
            "observed_at": first_seen,   # what we'd get reconstructing from store
            "ingested_at": first_seen,
            "sentiment": "positive",
            "sentiment_score": 0.9,
        },
    )
    store.save_news_event(e3)

    row = store.get_news_events()[0]
    # Mutable fields updated.
    assert row["sentiment"] == "positive"
    assert row["sentiment_score"] == 0.9
    # CRITICAL: last_seen_at did NOT regress.
    assert row["last_seen_at"] == to_iso_z(refetched_at)
    # First-seen timing also preserved.
    assert row["observed_at"] == to_iso_z(first_seen)
    assert row["ingested_at"] == to_iso_z(first_seen)


def test_store_init_adds_last_seen_at_to_existing_news_events_table(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"
    observed_at = datetime(2026, 5, 18, 15, 0, tzinfo=UTC).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE news_events (
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
                classified_at TEXT,
                event_type TEXT NOT NULL DEFAULT 'other',
                sentiment TEXT NOT NULL DEFAULT 'neutral',
                sentiment_score REAL NOT NULL DEFAULT 0.0,
                urgency TEXT NOT NULL DEFAULT 'normal',
                novelty_score REAL NOT NULL DEFAULT 0.0,
                source_credibility REAL NOT NULL DEFAULT 0.5,
                entities_json TEXT NOT NULL DEFAULT '[]',
                asset_scope_json TEXT NOT NULL DEFAULT '[]',
                index_exposure_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                model_outputs_json TEXT NOT NULL DEFAULT '[]',
                raw_artifact_path TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            INSERT INTO news_events(
                event_id, source, title, published_at, observed_at, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("evt_existing", "federalreserve.gov", "Statement A", observed_at, observed_at, observed_at),
        )

    Store(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(news_events)")}
        row = conn.execute("SELECT observed_at, last_seen_at FROM news_events WHERE event_id = ?", ("evt_existing",)).fetchone()

    assert "last_seen_at" in columns
    assert row == (observed_at, observed_at)
