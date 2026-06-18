from __future__ import annotations

from datetime import UTC, datetime

from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.enrichment.service import enrich_events
from trader.llm.client import LLMResponse
from trader.normalization.models import Event
from trader.storage.store import Store


def _event(event_id: str = "evt_service", source: str = "marketwatch.com") -> Event:
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    return Event(
        event_id=event_id,
        source=source,
        title="Fed comments move SPY",
        summary="Powell said the Fed will be patient on interest rates.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        asset_scope=["index", "macro"],
        index_exposure=["SPY"],
        event_type="fed_commentary",
        sentiment="neutral",
        sentiment_score=0.0,
        urgency="high",
        novelty_score=0.5,
        source_credibility=0.7,
    )


def _llm_response(event_id: str = "evt_service") -> LLMResponse:
    content = (
        '{"schema_version":"v1","prompt_template_version":"tmpl-v1",'
        f'"event_id":"{event_id}",'
        '"sentiment_label":"negative","sentiment_score":-0.4,'
        '"urgency":"high","novelty_score":0.8,"event_type":"fed_commentary",'
        '"key_claims":[{"text":"Powell signaled patience on rates.",'
        '"quote":"Powell said the Fed will be patient","from_field":"summary"}],'
        '"tickers_affected":["SPY"],"is_actionable":false,'
        '"confidence":0.82,"abstain_reason":null}'
    )
    return LLMResponse(
        content=content,
        parsed=None,
        model="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=50,
        cached_tokens=25,
        cache_creation_tokens=10,
        cost_usd=0.01,
        latency_ms=500,
        prompt_hash="abc123",
    )


class FakeLLM:
    def __init__(self, response: LLMResponse):
        self.response = response
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_enricher_persists_valid_output(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_news_event(_event())
    llm = FakeLLM(_llm_response())

    summary = enrich_events(store=store, llm=llm, limit=10, dry_run=False, daily_budget_usd=1.0)

    assert summary.seen == 1
    assert summary.enriched == 1
    assert summary.rejected == 0
    events = store.get_news_events_parsed()
    assert events[0].sentiment == "negative"
    assert events[0].sentiment_score == -0.4
    assert events[0].model_outputs[0].classifier == ENRICHER_CLASSIFIER
    assert events[0].model_outputs[0].prompt_version == PROMPT_TEMPLATE_VERSION
    assert llm.calls[0]["response_format_json"] is True


def test_enricher_dry_run_does_not_persist(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_news_event(_event())
    llm = FakeLLM(_llm_response())

    summary = enrich_events(store=store, llm=llm, limit=10, dry_run=True, daily_budget_usd=1.0)

    assert summary.seen == 1
    assert summary.enriched == 1
    event = store.get_news_events_parsed()[0]
    assert event.model_outputs == []


def test_enricher_respects_daily_budget(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_news_event(_event())
    store.record_llm_call(
        decision_id=None,
        brain="EventEnricher",
        model="claude-haiku-4-5-20251001",
        prompt_hash="existing",
        input_tokens=1,
        output_tokens=1,
        cached_tokens=0,
        cost_usd=1.0,
        latency_ms=1,
    )
    llm = FakeLLM(_llm_response())

    summary = enrich_events(store=store, llm=llm, limit=10, dry_run=False, daily_budget_usd=1.0)

    assert summary.seen == 0
    assert summary.skipped_budget == 1
    assert llm.calls == []


def test_enricher_rejects_invalid_model_output(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_news_event(_event())
    llm = FakeLLM(_llm_response(event_id="wrong_event"))

    summary = enrich_events(store=store, llm=llm, limit=10, dry_run=False, daily_budget_usd=1.0)

    assert summary.seen == 1
    assert summary.enriched == 0
    assert summary.rejected == 1
    event = store.get_news_events_parsed()[0]
    assert event.model_outputs[0].validation_status == "rejected"
