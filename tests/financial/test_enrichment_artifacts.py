from __future__ import annotations

from datetime import UTC, datetime

from trader.enrichment.artifacts import latest_enrichment_artifact, latest_enrichment_meta
from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Event, ModelOutputMeta


def _event(raw_output: str | None = None, *, status: str = "auto_passed") -> Event:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    event = Event(
        event_id="evt_artifact",
        source="demo_news",
        title="Apple raises guidance",
        summary="Apple raised guidance after services strength.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        event_type="guidance_raise",
        urgency="high",
    )
    if raw_output is not None:
        event.model_outputs.append(
            ModelOutputMeta(
                classifier=ENRICHER_CLASSIFIER,
                prompt_version=PROMPT_TEMPLATE_VERSION,
                raw_output=raw_output,
                validation_status=status,  # type: ignore[arg-type]
                created_at=now,
            )
        )
    return event


def _raw(event_id: str = "evt_artifact") -> str:
    return (
        '{"schema_version":"v1","prompt_template_version":"tmpl-v1",'
        f'"event_id":"{event_id}",'
        '"sentiment_label":"positive","sentiment_score":0.5,'
        '"urgency":"high","novelty_score":0.7,"event_type":"guidance_raise",'
        '"key_claims":[{"text":"Apple raised guidance.",'
        '"quote":"Apple raised guidance","from_field":"summary"}],'
        '"tickers_affected":["AAPL"],"is_actionable":true,'
        '"confidence":0.76,"abstain_reason":null}'
    )


def test_latest_enrichment_meta_returns_latest_matching_version():
    old = _event(_raw(), status="rejected")
    now = datetime(2026, 5, 20, 13, 0, tzinfo=UTC)
    old.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output=_raw(),
            validation_status="auto_passed",
            created_at=now,
        )
    )

    meta = latest_enrichment_meta(old)

    assert meta is not None
    assert meta.created_at == now
    assert meta.validation_status == "auto_passed"


def test_latest_enrichment_artifact_parses_valid_output():
    artifact = latest_enrichment_artifact(_event(_raw()))

    assert artifact is not None
    assert artifact.event_id == "evt_artifact"
    assert artifact.status == "auto_passed"
    assert artifact.sentiment_label == "positive"
    assert artifact.sentiment_score == 0.5
    assert artifact.tickers_affected == ["AAPL"]
    assert artifact.is_actionable is True
    assert artifact.confidence == 0.76


def test_latest_enrichment_artifact_returns_none_when_missing_or_invalid():
    assert latest_enrichment_artifact(_event()) is None
    assert latest_enrichment_artifact(_event("{not json")) is None
