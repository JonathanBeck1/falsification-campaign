from __future__ import annotations

from datetime import UTC, datetime

from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Event, ModelOutputMeta
from trader.storage.store import Store


def _event(event_id: str, source: str = "marketwatch.com") -> Event:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    return Event(
        event_id=event_id,
        source=source,
        title=f"Headline {event_id}",
        summary="Powell said rates remain restrictive.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        event_type="fed_commentary",
        urgency="high",
    )


def test_get_events_needing_enrichment_skips_existing_version(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    needs = _event("evt_needs")
    done = _event("evt_done")
    done.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output="{}",
            validation_status="auto_passed",
            created_at=datetime(2026, 5, 20, 13, 0, tzinfo=UTC),
        )
    )
    store.save_news_event(needs)
    store.save_news_event(done)

    candidates = store.get_events_needing_enrichment(
        classifier=ENRICHER_CLASSIFIER,
        prompt_version=PROMPT_TEMPLATE_VERSION,
        limit=10,
    )

    assert [event.event_id for event in candidates] == ["evt_needs"]


def test_update_news_event_enrichment_replaces_row(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    event = _event("evt_update")
    store.save_news_event(event)

    event.sentiment = "negative"
    event.sentiment_score = -0.5
    event.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output='{"ok": true}',
            validation_status="auto_passed",
            created_at=datetime(2026, 5, 20, 13, 0, tzinfo=UTC),
        )
    )
    store.update_news_event_enrichment(event)

    parsed = store.get_news_events_parsed()
    assert parsed[0].sentiment == "negative"
    assert parsed[0].sentiment_score == -0.5
    assert parsed[0].model_outputs[0].classifier == ENRICHER_CLASSIFIER
