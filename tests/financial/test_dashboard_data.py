from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from trader.dashboard.data import (
    StoreMetrics,
    attention_items,
    enrichment_status_counts,
    event_candidate_rows,
    event_type_counts,
    list_report_files,
    news_tape_rows,
    paper_intent_rows,
    recent_decision_rows,
    recent_events,
    recent_order_rows,
    report_file_rows,
    research_run_rows,
    source_counts,
    source_quality_rows,
    store_metrics,
    ticker_activity_rows,
)
from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.fed import fed_news_to_events
from trader.normalization.models import ModelOutputMeta
from trader.normalization.yahoo import yahoo_news_to_events
from trader.paper.intents import PaperTradeIntent
from trader.storage.snapshot import NewsItem
from trader.storage.store import Store


def _item(headline: str, *, source: str = "x", hour: int = 12) -> NewsItem:
    return NewsItem(
        headline=headline,
        source=source,
        published_at=datetime(2026, 5, 18, hour, 0, tzinfo=UTC),
    )


def test_dashboard_store_metrics_and_counts(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    for event in fed_news_to_events([_item("Fed holds rates", source="federalreserve.gov")]):
        store.save_news_event(event)
    for event in yahoo_news_to_events(
        [_item("What Nvidia Earnings Mean for QQQ", source="Yahoo")],
        queried_tickers=["QQQ", "NVDA"],
    ):
        store.save_news_event(event)

    metrics = store_metrics(store.db_path)

    assert metrics.total_events == 2
    assert metrics.total_decisions == 0
    assert metrics.total_orders == 0
    assert metrics.latest_event_at is not None
    assert source_counts(store.db_path)[0]["source"] == "federalreserve.gov"
    assert {"event_type": "earnings_surprise", "count": 1} in event_type_counts(store.db_path)


def test_dashboard_recent_events(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    events = yahoo_news_to_events(
        [
            _item("Older market story", hour=10),
            _item("Former Fed Official: rate cuts were a mistake", hour=13),
        ],
        queried_tickers=["SPY"],
    )
    for event in events:
        store.save_news_event(event)

    rows = recent_events(store.db_path, limit=1)

    assert len(rows) == 1
    assert rows[0]["title"] == "Former Fed Official: rate cuts were a mistake"
    assert rows[0]["event_type"] == "fed_commentary"


def test_dashboard_list_report_files(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "b.md").write_text("# B\n", encoding="utf-8")
    (reports / "a.txt").write_text("ignore\n", encoding="utf-8")
    (reports / "c.md").write_text("# C\n", encoding="utf-8")

    files = list_report_files(reports)

    assert [file.name for file in files] == ["c.md", "b.md"]


def test_dashboard_report_file_rows_include_terminal_metadata(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    outcome = reports / "spy-outcome-review.md"
    outcome.write_text("# Outcome Review\n", encoding="utf-8")
    daily = reports / "daily-brief.md"
    daily.write_text("# Daily Brief\n", encoding="utf-8")
    (reports / "ignore.txt").write_text("ignore\n", encoding="utf-8")
    os.utime(outcome, (1_700_000_000, 1_700_000_000))
    os.utime(daily, (1_700_000_100, 1_700_000_100))

    rows = report_file_rows(reports)

    assert [row["name"] for row in rows] == ["daily-brief.md", "spy-outcome-review.md"]
    assert rows[0]["category"] == "daily"
    assert rows[1]["category"] == "outcome_review"
    assert rows[0]["size_bytes"] > 0
    assert rows[0]["modified_at"] == "2023-11-14T22:15:00+00:00"


def test_dashboard_attention_items_surface_terminal_work():
    items = attention_items(
        metrics=None,
        enrichment=[],
        candidates=[{"ticker": "SPY", "score": 84}],
        reports=[],
        system_events=[{"level": "error", "message": "feed failed"}],
        source_quality=[{"source": "fed", "latest_status": "error", "latest_error": "timeout"}],
    )

    labels = [item["label"] for item in items]

    assert "Database missing" in labels
    assert "Candidates waiting" in labels
    assert "Reports missing" in labels
    assert "System errors" in labels
    assert "Source fetch failed" in labels


def test_dashboard_attention_items_quiet_when_no_action_needed():
    metrics = StoreMetrics(total_events=10, total_decisions=0, total_orders=0, latest_event_at="2026-05-18T12:00:00Z")

    items = attention_items(
        metrics=metrics,
        enrichment=[{"bucket": "enriched", "count": 10}],
        candidates=[],
        reports=[{"name": "daily.md"}],
        system_events=[],
    )

    assert items == [
        {
            "level": "success",
            "label": "Pipeline quiet",
            "detail": "No immediate operator action detected.",
        }
    ]


def test_dashboard_news_tape_rows_parse_tickers(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    event = yahoo_news_to_events([_item("SPY and QQQ move after Fed rate comments")], queried_tickers=["SPY", "QQQ"])[0]
    store.save_news_event(event)

    rows = news_tape_rows(store.db_path, limit=5)

    assert rows[0]["event_id"] == event.event_id
    assert rows[0]["tickers"] == "QQQ, SPY"
    assert rows[0]["event_type"] == "fed_commentary"
    assert rows[0]["urgency"] == "high"
    assert rows[0]["title"] == "SPY and QQQ move after Fed rate comments"


def test_dashboard_ticker_activity_rows_aggregate_event_flow(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    for event in yahoo_news_to_events(
        [_item("SPY rallies after Fed comments"), _item("QQQ earnings read-through", hour=13)],
        queried_tickers=["SPY", "QQQ"],
    ):
        store.save_news_event(event)

    rows = ticker_activity_rows(store.db_path, limit=5)

    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["SPY"]["event_count"] == 2
    assert by_ticker["QQQ"]["event_count"] == 2
    assert by_ticker["SPY"]["latest_title"] == "QQQ earnings read-through"


def test_dashboard_recent_decision_and_order_rows(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_snapshot("snap-1", "2026-05-18", "SPY", {"close": 500})
    decision_id = store.save_decision(
        snapshot_id="snap-1",
        brain="ClassicalBrain",
        action="BUY",
        target_pct=0.5,
        confidence=0.7,
        reasoning="trend up",
        llm_cost_usd=0.0,
    )
    store.record_order(
        client_order_id="order-1",
        decision_id=decision_id,
        brain="ClassicalBrain",
        ticker="SPY",
        side="buy",
        qty=3,
        order_type="market",
        limit_price=None,
        alpaca_order_id="alpaca-1",
    )

    decision_rows = recent_decision_rows(store.db_path, limit=5)
    order_rows = recent_order_rows(store.db_path, limit=5)

    assert decision_rows[0]["brain"] == "ClassicalBrain"
    assert decision_rows[0]["action"] == "BUY"
    assert order_rows[0]["ticker"] == "SPY"
    assert order_rows[0]["status"] == "submitted"


def test_dashboard_enrichment_status_counts(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    events = yahoo_news_to_events([_item("Stocks move after Fed comments")], queried_tickers=["SPY"])
    missing = events[0]
    store.save_news_event(missing)

    enriched = yahoo_news_to_events([_item("Apple raises guidance", hour=13)], queried_tickers=["AAPL"])[0]
    enriched.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output=(
                '{"schema_version":"v1","prompt_template_version":"tmpl-v1","event_id":"'
                + enriched.event_id
                + '","sentiment_label":"positive","sentiment_score":0.4,'
                '"urgency":"high","novelty_score":0.7,"event_type":"guidance_raise",'
                '"key_claims":[{"text":"Apple raised guidance.","quote":"Apple raises guidance","from_field":"title"}],'
                '"tickers_affected":["AAPL"],"is_actionable":true,"confidence":0.7,"abstain_reason":null}'
            ),
            validation_status="auto_passed",
            created_at=datetime(2026, 5, 18, 13, 1, tzinfo=UTC),
        )
    )
    store.save_news_event(enriched)

    counts = enrichment_status_counts(store.db_path)

    assert {"bucket": "enriched", "count": 1} in counts
    assert {"bucket": "missing", "count": 1} in counts


def test_dashboard_event_candidate_rows(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    event = yahoo_news_to_events([_item("Apple raises guidance", hour=13)], queried_tickers=["AAPL"])[0]
    event.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output=(
                '{"schema_version":"v1","prompt_template_version":"tmpl-v1","event_id":"'
                + event.event_id
                + '","sentiment_label":"positive","sentiment_score":0.5,'
                '"urgency":"high","novelty_score":0.7,"event_type":"guidance_raise",'
                '"key_claims":[{"text":"Apple raised guidance.","quote":"Apple raises guidance","from_field":"title"}],'
                '"tickers_affected":["AAPL"],"is_actionable":true,"confidence":0.76,"abstain_reason":null}'
            ),
            validation_status="auto_passed",
            created_at=datetime(2026, 5, 18, 13, 1, tzinfo=UTC),
        )
    )
    store.save_news_event(event)

    rows = event_candidate_rows(store.db_path, limit=5)

    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["direction"] == "bullish"
    assert rows[0]["score"] > 50


def test_dashboard_research_run_rows(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    run_id = store.create_research_run(
        command={"command": "research-cycle"},
        benchmark="SPY",
        entry_time="observed_at",
        horizons="5m",
        group_by="event_type",
        since=None,
        until=None,
        data_provider="yahoo",
        events_before=0,
    )
    store.finish_research_run(
        run_id,
        status="succeeded",
        events_after=2,
        enriched_count=1,
        rejected_count=0,
        candidate_count=1,
        outcome_report_path="output/reports/outcomes.md",
        review_report_path="output/reports/outcome-review.md",
        manifest_path="output/reports/manifest.md",
    )

    rows = research_run_rows(store.db_path, limit=5)

    assert rows[0]["run_id"] == run_id
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["candidate_count"] == 1


def test_dashboard_research_run_rows_handles_older_database(tmp_path: Path):
    db_path = tmp_path / "empty.sqlite"

    rows = research_run_rows(db_path, limit=5)

    assert rows == []


def test_dashboard_source_quality_rows_summarize_fetch_ledger(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    failed = store.start_source_fetch("fed", lookback_days=90)
    store.finish_source_fetch(failed, status="error", item_count=0, persisted_count=0, latency_ms=12, error="timeout")
    ok = store.start_source_fetch("yahoo_news", lookback_days=3)
    store.finish_source_fetch(ok, status="ok", item_count=8, persisted_count=5, latency_ms=34)

    rows = source_quality_rows(store.db_path, limit=10)

    by_source = {row["source"]: row for row in rows}
    assert by_source["fed"]["latest_status"] == "error"
    assert by_source["fed"]["latest_error"] == "timeout"
    assert by_source["fed"]["health"] == "failing"
    assert by_source["yahoo_news"]["latest_persisted_count"] == 5
    assert by_source["yahoo_news"]["health"] == "healthy"


def test_dashboard_source_quality_rows_handles_older_database(tmp_path: Path):
    db_path = tmp_path / "empty.sqlite"

    rows = source_quality_rows(db_path, limit=5)

    assert rows == []


def test_dashboard_paper_intent_rows(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_paper_trade_intent(
        PaperTradeIntent(
            intent_id="intent-1",
            event_id="event-1",
            created_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
            ticker="QQQ",
            direction="bullish",
            candidate_score=72,
            confidence=0.8,
            proposed_action="BUY",
            proposed_target_pct=0.25,
            risk_status="approved",
            risk_reason="target 25%",
            final_action="BUY",
            final_qty=3,
            status="staged",
            source="demo_news",
            event_type="guidance_raise",
            title="Apple raises guidance",
        )
    )

    rows = paper_intent_rows(store.db_path, limit=5)

    assert rows[0]["intent_id"] == "intent-1"
    assert rows[0]["ticker"] == "QQQ"
    assert rows[0]["status"] == "staged"
    assert rows[0]["risk_status"] == "approved"
    assert rows[0]["title"] == "Apple raises guidance"


def test_dashboard_paper_intent_rows_handles_older_database(tmp_path: Path):
    db_path = tmp_path / "empty.sqlite"

    rows = paper_intent_rows(db_path, limit=5)

    assert rows == []
