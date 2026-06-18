from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from trader.ingestion.events import fetch_and_persist_events, persist_source_events
from trader.ingestion.source_health import CompositeSourceTracker, StoreSourceHealthTracker
from trader.storage.snapshot import NewsItem
from trader.storage.store import Store


class _MemoryTracker:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.fetches: list[tuple[str, int, str | None]] = []
        self.persisted: dict[str, int] = {}

    def start_fetch(self, source: str) -> None:
        self.started.append(source)

    def record_fetch(self, source: str, *, item_count: int, error: str | None = None) -> None:
        self.fetches.append((source, item_count, error))

    def record_persisted_counts(self, counts: dict[str, int]) -> None:
        self.persisted.update(counts)


def _item(headline: str, source: str = "yahoo") -> NewsItem:
    return NewsItem(
        headline=headline,
        source=source,
        published_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
    )


def test_store_source_health_tracker_records_ok_empty_error_and_persisted(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    tracker = StoreSourceHealthTracker(store, lookback_days=7)

    tracker.start_fetch("yahoo_news")
    tracker.record_fetch("yahoo_news", item_count=3)
    tracker.record_persisted_counts({"yahoo_news": 2})
    tracker.start_fetch("fed")
    tracker.record_fetch("fed", item_count=0)
    tracker.start_fetch("finnhub")
    tracker.record_fetch("finnhub", item_count=0, error="rate limited")

    summary = {row["source"]: row for row in store.source_fetch_summary(limit=10)}

    assert summary["yahoo_news"]["latest_status"] == "ok"
    assert summary["yahoo_news"]["latest_item_count"] == 3
    assert summary["yahoo_news"]["latest_persisted_count"] == 2
    assert summary["fed"]["latest_status"] == "empty"
    assert summary["finnhub"]["latest_status"] == "error"
    assert summary["finnhub"]["latest_error"] == "rate limited"


def test_composite_source_tracker_fans_out_fetch_and_persisted_counts():
    one = _MemoryTracker()
    two = _MemoryTracker()
    tracker = CompositeSourceTracker(one, two)

    tracker.start_fetch("web_news")
    tracker.record_fetch("web_news", item_count=4)
    tracker.record_persisted_counts({"web_news": 3})

    assert one.started == ["web_news"]
    assert two.started == ["web_news"]
    assert one.fetches == [("web_news", 4, None)]
    assert two.persisted == {"web_news": 3}


def test_persist_source_events_records_persisted_counts(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    tracker = StoreSourceHealthTracker(store, lookback_days=3)
    tracker.start_fetch("yahoo_news")
    tracker.record_fetch("yahoo_news", item_count=1)

    counts = persist_source_events(
        store=store,
        by_source={
            "finnhub": [],
            "alpaca_news": [],
            "yahoo_news": [_item("SPY moves after Fed comments")],
            "sec_edgar": [],
            "fed": [],
            "web_news": [],
        },
        ticker="SPY",
        context_tickers=["SPY"],
        source_tracker=tracker,
    )

    row = store.source_fetch_summary(limit=10)[0]
    assert counts["yahoo_news"] == 1
    assert row["source"] == "yahoo_news"
    assert row["latest_persisted_count"] == 1


def test_fetch_and_persist_events_uses_tracker_for_fetch_and_persist_counts(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "trader.sqlite")
    tracker = StoreSourceHealthTracker(store, lookback_days=30)

    def fake_fetch(ticker, context_tickers, sec_tickers, *, lookback_days=None, heartbeat=None):
        assert lookback_days == 30
        assert heartbeat is tracker
        heartbeat.start_fetch("yahoo_news")
        heartbeat.record_fetch("yahoo_news", item_count=1)
        return {
            "finnhub": [],
            "alpaca_news": [],
            "yahoo_news": [_item("SPY and QQQ rally")],
            "sec_edgar": [],
            "fed": [],
            "web_news": [],
        }

    monkeypatch.setattr("trader.ingestion.events.fetch_source_news", fake_fetch)

    counts = fetch_and_persist_events(
        store=store,
        ticker="SPY",
        context_tickers=["SPY", "QQQ"],
        sec_tickers=[],
        lookback_days=30,
        source_tracker=tracker,
    )

    summary = {row["source"]: row for row in store.source_fetch_summary(limit=10)}
    assert counts["yahoo_news"] == 1
    assert summary["yahoo_news"]["latest_status"] == "ok"
    assert summary["yahoo_news"]["latest_persisted_count"] == 1
