from __future__ import annotations

from datetime import UTC, datetime

from trader.ingestion.events import fetch_and_persist_events
from trader.storage.snapshot import NewsItem
from trader.storage.store import Store


def _item(headline: str, source: str) -> NewsItem:
    return NewsItem(
        headline=headline,
        source=source,
        published_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
    )


def test_persist_isolates_one_bad_event(tmp_path, monkeypatch):
    """One save_news_event failure must NOT abort the rest of the batch.

    Previously persist_source_events looped over events and called
    save_news_event without an inner try/except. A single malformed row
    (bad JSON, None title, etc.) would raise out of the loop and zero out
    every later source — undoing the fetch-side isolation _safe_fetch_source
    provides. This test pins the new per-event isolation.
    """
    from trader.ingestion.events import persist_source_events

    store = Store(tmp_path / "trader.sqlite")

    # Wrap save_news_event so the second item we feed in raises.
    call_count = {"n": 0}
    original_save = store.save_news_event

    def flaky_save(event):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated DB write failure for one event")
        return original_save(event)

    monkeypatch.setattr(store, "save_news_event", flaky_save)

    finnhub_items = [
        _item("AAPL beats Q2 estimates", "finnhub"),
        _item("Microsoft raises guidance", "finnhub"),  # will fail
        _item("Tesla announces battery breakthrough", "finnhub"),
    ]

    counts = persist_source_events(
        store=store,
        by_source={
            "finnhub": finnhub_items,
            "alpaca_news": [],
            "yahoo_news": [],
            "sec_edgar": [],
            "fed": [],
            "web_news": [],
        },
        ticker="AAPL",
        context_tickers=["AAPL"],
    )

    # Two of three finnhub items persisted (one was sabotaged).
    assert counts["finnhub"] == 2
    assert store.count_news_events(source="finnhub") == 2


def test_fetch_and_persist_events_stores_events_without_decisions(tmp_path, monkeypatch):
    store = Store(tmp_path / "trader.sqlite")

    monkeypatch.setattr(
        "trader.ingestion.events.fetch_source_news",
        lambda ticker, context_tickers, sec_tickers, *, lookback_days=None: {
            "finnhub": [_item("AAPL beats Q2 estimates", "finnhub")],
            "alpaca_news": [],
            "yahoo_news": [],
            "sec_edgar": [],
            "fed": [],
            "web_news": [],
        },
    )

    counts = fetch_and_persist_events(
        store=store,
        ticker="AAPL",
        context_tickers=["AAPL"],
        sec_tickers=[],
    )

    assert counts == {
        "finnhub": 1,
        "alpaca_news": 0,
        "yahoo_news": 0,
        "sec_edgar": 0,
        "fed": 0,
        "web_news": 0,
    }
    assert store.count_news_events(source="finnhub") == 1
    assert store.get_decisions_for_brain("ClassicalBrain") == []


def test_fetch_and_persist_events_forwards_lookback_days(tmp_path, monkeypatch):
    """The --lookback-days CLI flag must reach the source adapters or the
    Milestone 1 Fed/SPY first-event-report can't be unblocked."""
    store = Store(tmp_path / "trader.sqlite")
    captured: dict = {}

    def fake_fetch(ticker, context_tickers, sec_tickers, *, lookback_days=None):
        captured["lookback_days"] = lookback_days
        return {k: [] for k in ("finnhub", "alpaca_news", "yahoo_news", "sec_edgar", "fed", "web_news")}

    monkeypatch.setattr("trader.ingestion.events.fetch_source_news", fake_fetch)

    fetch_and_persist_events(
        store=store, ticker="SPY", context_tickers=["SPY", "QQQ"], sec_tickers=[], lookback_days=180
    )
    assert captured["lookback_days"] == 180
