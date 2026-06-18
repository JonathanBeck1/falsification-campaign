"""Tests for the web-news adapter and normalizer.

Network is mocked at the Scrapling `Fetcher.get` / `StealthyFetcher.fetch`
boundary — no real publishers are hit. See `brain/17_news_web_spider_proposal.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

# The web-news adapter's fetcher is an optional dependency (`pip install -e
# ".[scraping]"`). Skip this module's tests when it isn't installed.
pytest.importorskip("scrapling")

from trader.adapters.news import web as web_adapter
from trader.adapters.news.web import (
    DEFAULT_SOURCES,
    SourceConfig,
    _is_relevant,
    _parse_rss,
    fetch_web_news,
)
from trader.normalization.web import web_news_to_events
from trader.storage.snapshot import NewsItem


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rss_with_items(*items: tuple[str, str, str]) -> str:
    body = "".join(
        f"<item><title>{_xml_escape(title)}</title><link>{_xml_escape(link)}</link>"
        f"<description>{_xml_escape(desc)}</description>"
        f"<pubDate>Tue, 19 May 2026 13:14:14 GMT</pubDate></item>"
        for title, link, desc in items
    )
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>"


class _FakeResp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status = status


# ---------- pure-function tests ----------


def test_is_relevant_matches_index_keywords():
    assert _is_relevant("S&P 500 hits new high", "")
    assert _is_relevant("QQQ leads tech rally", "Index futures up")
    assert _is_relevant("Fed minutes show split", "")
    assert _is_relevant("", "wall street braces for cpi print")


def test_is_relevant_rejects_single_name_news():
    # Apple-earnings without any index/macro hook should not pass the broad-market filter.
    assert not _is_relevant("Apple beats on iPhone revenue", "AAPL crushed estimates")
    assert not _is_relevant("Boeing delivers 737", "")


def test_parse_rss_skips_items_missing_title_or_date():
    xml = (
        "<?xml version='1.0'?><rss><channel>"
        "<item><title>Good one</title><link>http://x.test/a</link>"
        "<description>x</description><pubDate>Tue, 19 May 2026 13:14:14 GMT</pubDate></item>"
        "<item><link>http://x.test/b</link><pubDate>Tue, 19 May 2026 13:14:14 GMT</pubDate></item>"
        "<item><title>No date</title><link>http://x.test/c</link></item>"
        "</channel></rss>"
    )
    rows = _parse_rss(xml)
    assert len(rows) == 1
    assert rows[0][0] == "Good one"


def test_parse_rss_handles_malformed_xml():
    assert _parse_rss("not xml at all") == []


# ---------- adapter tests with mocked fetcher ----------


def test_fetch_web_news_happy_path(monkeypatch):
    rss = _rss_with_items(
        ("S&P 500 rallies on Fed pivot", "http://mw.test/a", "Stocks jump on rate cut hopes"),
        ("Apple iPhone shipments slip", "http://mw.test/b", "Single-name story — should be filtered"),
        ("Nasdaq 100 closes at record", "http://mw.test/c", "QQQ leads tech surge"),
    )

    def fake_get(url, timeout=10.0):
        return _FakeResp(text=rss, status=200)

    monkeypatch.setattr(web_adapter, "_fetch_rss", lambda src, timeout=10.0: rss)

    src = SourceConfig(name="test.example", rss_url="http://test/feed", credibility=0.6)
    items = fetch_web_news(sources=(src,), lookback_days=None)

    titles = [i.headline for i in items]
    assert "S&P 500 rallies on Fed pivot" in titles
    assert "Nasdaq 100 closes at record" in titles
    assert "Apple iPhone shipments slip" not in titles  # filtered out by relevance check
    for item in items:
        assert item.source == "test.example"


def test_fetch_web_news_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(web_adapter, "_fetch_rss", lambda src, timeout=10.0: None)
    src = SourceConfig(name="broken.example", rss_url="http://broken/feed")
    assert fetch_web_news(sources=(src,), lookback_days=None) == []


def test_fetch_rss_sends_configured_user_agent(monkeypatch):
    calls = {}

    class FakeResp:
        status = 200
        body = b"<?xml version='1.0'?><rss><channel /></rss>"

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls.update(kwargs)
        return FakeResp()

    import scrapling

    monkeypatch.setattr(scrapling.Fetcher, "get", fake_get)
    monkeypatch.setattr(web_adapter, "_user_agent", lambda: "trader test@example.com")

    src = SourceConfig(name="ua.example", rss_url="http://ua.example/feed")
    xml = web_adapter._fetch_rss(src, timeout=3.5)

    assert calls["url"] == "http://ua.example/feed"
    assert calls["timeout"] == 3.5
    assert calls["headers"] == {"User-Agent": "trader test@example.com"}
    assert xml is not None


def test_fetch_web_news_dedups_across_sources(monkeypatch):
    duplicate_rss = _rss_with_items(
        ("S&P 500 rallies on Fed pivot", "http://a.test/x", "same title"),
    )
    monkeypatch.setattr(web_adapter, "_fetch_rss", lambda src, timeout=10.0: duplicate_rss)
    sources = (
        SourceConfig(name="a.test", rss_url="http://a/feed"),
        SourceConfig(name="b.test", rss_url="http://b/feed"),
    )
    items = fetch_web_news(sources=sources, lookback_days=None)
    # Same (host, title) only kept once. Both rss feeds resolve to link host a.test.
    assert len(items) == 1


def test_fetch_web_news_respects_lookback_days(monkeypatch):
    # All RSS items have pubDate 2026-05-19. With lookback_days=1 from a far-future
    # current time, they should all be filtered out.
    rss = _rss_with_items(
        ("S&P 500 rallies on Fed pivot", "http://x.test/a", "stocks"),
    )
    monkeypatch.setattr(web_adapter, "_fetch_rss", lambda src, timeout=10.0: rss)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 1, tzinfo=UTC)

    with patch.object(web_adapter, "datetime", _FixedDatetime):
        items = fetch_web_news(
            sources=(SourceConfig(name="x.test", rss_url="http://x/feed"),),
            lookback_days=1,
        )
    assert items == []


def test_fetch_web_news_invokes_stealthy_fetcher_when_configured(monkeypatch):
    rss = _rss_with_items(("Fed minutes show split", "http://x.test/a", "short summary"))
    monkeypatch.setattr(web_adapter, "_fetch_rss", lambda src, timeout=10.0: rss)

    called = {}

    def fake_article(url, selectors):
        called["url"] = url
        called["selectors"] = selectors
        return "Full article body extracted via StealthyFetcher."

    monkeypatch.setattr(web_adapter, "_fetch_article_body", fake_article)

    src = SourceConfig(
        name="x.test",
        rss_url="http://x/feed",
        fetch_full_article=True,
        article_selectors=("article.body",),
    )
    items = fetch_web_news(sources=(src,), lookback_days=None)
    assert len(items) == 1
    assert items[0].summary.startswith("Full article body extracted")
    assert called["url"] == "http://x.test/a"
    assert called["selectors"] == ("article.body",)


def test_fetch_web_news_skips_stealthy_fetcher_by_default(monkeypatch):
    rss = _rss_with_items(("Fed minutes show split", "http://x.test/a", "rss summary text"))
    monkeypatch.setattr(web_adapter, "_fetch_rss", lambda src, timeout=10.0: rss)

    def fail_if_called(url, selectors):
        raise AssertionError("StealthyFetcher must not be invoked when fetch_full_article=False")

    monkeypatch.setattr(web_adapter, "_fetch_article_body", fail_if_called)

    src = SourceConfig(name="x.test", rss_url="http://x/feed", fetch_full_article=False)
    items = fetch_web_news(sources=(src,), lookback_days=None)
    assert items[0].summary == "rss summary text"


def test_default_sources_are_configured():
    assert len(DEFAULT_SOURCES) >= 2
    for src in DEFAULT_SOURCES:
        assert src.rss_url.startswith("http")
        assert 0 <= src.credibility <= 1


# ---------- normalizer tests ----------


@pytest.fixture
def sample_items() -> list[NewsItem]:
    now = datetime(2026, 5, 19, 13, 14, 14, tzinfo=UTC)
    return [
        NewsItem(
            headline="Fed minutes show split on rate path",
            summary="FOMC participants debated cuts.",
            source="marketwatch.com",
            published_at=now,
        ),
        NewsItem(
            headline="QQQ leads tech rally",
            summary="Nasdaq closes at record.",
            source="unknown-host.test",
            published_at=now + timedelta(minutes=5),
        ),
    ]


def test_web_news_to_events_basic(sample_items):
    events = web_news_to_events(sample_items, queried_tickers=["SPY", "QQQ"])
    assert len(events) == 2
    fed_event, tech_event = events

    assert fed_event.source == "marketwatch.com"
    assert fed_event.source_credibility == 0.7  # mapped credibility
    assert fed_event.event_type == "fed_commentary"
    assert fed_event.asset_scope == ["index", "macro"]
    assert fed_event.index_exposure == ["QQQ", "SPY"]  # sorted alphabetically

    assert tech_event.source == "unknown-host.test"
    assert tech_event.source_credibility == 0.55  # fallback for unmapped hosts


def test_web_news_to_events_event_ids_stable(sample_items):
    events_a = web_news_to_events(sample_items, queried_tickers=["SPY", "QQQ"])
    events_b = web_news_to_events(sample_items, queried_tickers=["SPY", "QQQ"])
    assert [e.event_id for e in events_a] == [e.event_id for e in events_b]


def test_web_news_to_events_empty():
    assert web_news_to_events([], queried_tickers=["SPY", "QQQ"]) == []
