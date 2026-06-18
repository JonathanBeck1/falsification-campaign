from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.alpaca_news import alpaca_news_to_events
from trader.normalization.fed import fed_news_to_events
from trader.normalization.finnhub import finnhub_news_to_events
from trader.normalization.sec import sec_news_to_events
from trader.normalization.web import web_news_to_events
from trader.normalization.yahoo import yahoo_news_to_events
from trader.storage.snapshot import NewsItem


def _item(headline: str, source: str = "test.source") -> NewsItem:
    return NewsItem(
        headline=headline,
        summary="Fed rate path and market reaction.",
        source=source,
        published_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
    )


def test_all_normalizers_stamp_classified_at():
    """Per Codex re-review (2026-05-20): classified_at must use the
    caller-controlled observed_at, NOT wall-clock now(). Otherwise
    replay/backfill stamps historical events with the *future*
    classified_at of the replay run, and point-in-time retrieval
    (which drops rows where classified_at >= as_of) silently excludes
    them.

    Earlier version asserted started_at <= classified_at <= finished_at
    — i.e., that classified_at lived in the live-run window. That
    pinned the bug, not the fix."""
    observed_at = datetime(2026, 5, 20, 13, 0, tzinfo=UTC)

    batches = [
        finnhub_news_to_events([_item("AAPL beats Q2 estimates")], ticker="AAPL", observed_at=observed_at),
        alpaca_news_to_events([_item("SPY moves after Fed comments")], queried_symbols=["SPY"], observed_at=observed_at),
        yahoo_news_to_events([_item("FOMC statement moves stocks")], queried_tickers=["SPY"], observed_at=observed_at),
        fed_news_to_events(
            [_item("Federal Reserve issues FOMC statement", "federalreserve.gov")],
            observed_at=observed_at,
        ),
        sec_news_to_events([_item("AAPL 8-K filing", "sec_edgar")], observed_at=observed_at),
        web_news_to_events(
            [_item("S&P 500 rallies on Fed pivot", "marketwatch.com")],
            queried_tickers=["SPY"],
            observed_at=observed_at,
        ),
    ]

    events = [event for batch in batches for event in batch]
    assert events
    assert all(isinstance(event.classified_at, datetime) for event in events)
    # Key invariant: classified_at == observed_at for the
    # caller-controlled path. This makes replay/backfill safe.
    assert all(event.classified_at == observed_at for event in events)


def test_normalizers_default_classified_at_to_now_when_observed_at_unset():
    """When the caller doesn't supply observed_at, normalizers fall back
    to datetime.now(UTC) for both observed_at and classified_at."""
    started_at = datetime.now(UTC)
    events = fed_news_to_events([_item("Powell speech", "federalreserve.gov")])
    finished_at = datetime.now(UTC)
    assert events
    for e in events:
        assert e.classified_at is not None
        assert e.observed_at == e.classified_at
        assert started_at <= e.classified_at <= finished_at
