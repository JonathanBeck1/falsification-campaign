"""Tests for the Yahoo Finance news adapter.

We never hit the real Yahoo endpoint in tests — we mock `yfinance.Ticker` so the
behavior is deterministic and offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from trader.adapters.news.yahoo import (
    _parse_pubdate,
    _to_news_item,
    fetch_yahoo_news,
    merge_news,
)
from trader.storage.snapshot import NewsItem

# ── _parse_pubdate ────────────────────────────────────────────────────────────


def test_parse_pubdate_unix_int():
    dt = _parse_pubdate(1_700_000_000)
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_pubdate_iso_z():
    dt = _parse_pubdate("2026-05-18T14:30:00Z")
    assert dt == datetime(2026, 5, 18, 14, 30, tzinfo=UTC)


def test_parse_pubdate_none_and_garbage():
    assert _parse_pubdate(None) is None
    assert _parse_pubdate("not a date") is None
    assert _parse_pubdate(object()) is None


# ── _to_news_item — both yfinance schemas ────────────────────────────────────


def test_to_news_item_legacy_schema():
    raw = {
        "title": "QQQ rallies on Fed news",
        "summary": "Big moves today.",
        "publisher": "Reuters",
        "providerPublishTime": 1_700_000_000,
    }
    item = _to_news_item(raw)
    assert isinstance(item, NewsItem)
    assert item.headline == "QQQ rallies on Fed news"
    assert item.source == "Reuters"


def test_to_news_item_new_schema():
    raw = {
        "id": "abc",
        "content": {
            "title": "SPY drops on jobs report",
            "summary": "Weak NFP.",
            "pubDate": "2026-05-18T14:30:00Z",
            "provider": {"displayName": "Bloomberg"},
        },
    }
    item = _to_news_item(raw)
    assert item is not None
    assert item.headline == "SPY drops on jobs report"
    assert item.source == "Bloomberg"
    assert item.published_at == datetime(2026, 5, 18, 14, 30, tzinfo=UTC)


def test_to_news_item_missing_title_returns_none():
    assert _to_news_item({"publisher": "X", "providerPublishTime": 1}) is None


def test_to_news_item_missing_date_returns_none():
    assert _to_news_item({"title": "Headline only", "publisher": "X"}) is None


def test_to_news_item_uses_description_fallback():
    raw = {
        "content": {
            "title": "Hello",
            "description": "Fallback body",
            "pubDate": "2026-05-18T14:30:00Z",
        }
    }
    item = _to_news_item(raw)
    assert item is not None
    assert item.summary == "Fallback body"


# ── fetch_yahoo_news ─────────────────────────────────────────────────────────


def _mock_ticker(news_list):
    class _T:
        def __init__(self, *args, **kwargs):
            self.news = news_list

    return _T


def test_fetch_yahoo_news_happy_path():
    fake_news = [
        {
            "content": {
                "title": "Story 1",
                "pubDate": "2026-05-18T10:00:00Z",
                "provider": {"displayName": "Reuters"},
            }
        },
        {
            "content": {
                "title": "Story 2",
                "pubDate": "2026-05-18T12:00:00Z",
                "provider": {"displayName": "WSJ"},
            }
        },
    ]
    with patch("yfinance.Ticker", _mock_ticker(fake_news)):
        items = fetch_yahoo_news(["QQQ"])
    assert len(items) == 2
    # Sorted oldest-first
    assert items[0].headline == "Story 1"
    assert items[1].headline == "Story 2"


def test_fetch_yahoo_news_dedupes_across_tickers():
    """Same story showing up under both QQQ and SPY should appear once."""
    shared = {
        "content": {
            "title": "Fed holds rates",
            "pubDate": "2026-05-18T18:00:00Z",
            "provider": {"displayName": "Reuters"},
        }
    }
    with patch("yfinance.Ticker", _mock_ticker([shared])):
        items = fetch_yahoo_news(["QQQ", "SPY"])
    assert len(items) == 1


def test_fetch_yahoo_news_swallows_exceptions():
    class _BoomTicker:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("network down")

    with patch("yfinance.Ticker", _BoomTicker):
        items = fetch_yahoo_news(["QQQ", "SPY"])
    assert items == []


def test_fetch_yahoo_news_skips_unparseable_entries():
    bad = [
        {"this": "is not news"},
        {"content": {"title": "", "pubDate": "2026-05-18T10:00:00Z"}},  # empty title
        {
            "content": {
                "title": "Real one",
                "pubDate": "2026-05-18T10:00:00Z",
            }
        },
    ]
    with patch("yfinance.Ticker", _mock_ticker(bad)):
        items = fetch_yahoo_news(["QQQ"])
    assert len(items) == 1
    assert items[0].headline == "Real one"


def test_fetch_yahoo_news_per_ticker_limit():
    many = [
        {
            "content": {
                "title": f"Story {i}",
                "pubDate": f"2026-05-18T{i:02d}:00:00Z",
            }
        }
        for i in range(20)
    ]
    with patch("yfinance.Ticker", _mock_ticker(many)):
        items = fetch_yahoo_news(["QQQ"], per_ticker_limit=5)
    assert len(items) == 5


# ── merge_news ───────────────────────────────────────────────────────────────


def _make(headline: str, hour: int = 10) -> NewsItem:
    return NewsItem(
        headline=headline,
        summary="",
        source="test",
        published_at=datetime(2026, 5, 18, hour, 0, tzinfo=UTC),
    )


def test_merge_news_dedupes_case_insensitive():
    a = [_make("Fed cuts rates", 10)]
    b = [_make("FED CUTS RATES", 11)]  # same story, different case
    merged = merge_news(a, b)
    assert len(merged) == 1
    assert merged[0].source == "test"  # from `a`, since it came first


def test_merge_news_sorts_oldest_first():
    a = [_make("Later headline", 14)]
    b = [_make("Earlier headline", 9)]
    merged = merge_news(a, b)
    assert merged[0].headline == "Earlier headline"
    assert merged[1].headline == "Later headline"


def test_merge_news_empty_sources():
    assert merge_news([], []) == []


def test_merge_news_three_sources():
    merged = merge_news(
        [_make("A", 10)],
        [_make("B", 11), _make("A", 12)],  # dup A
        [_make("C", 9)],
    )
    assert [n.headline for n in merged] == ["C", "A", "B"]
