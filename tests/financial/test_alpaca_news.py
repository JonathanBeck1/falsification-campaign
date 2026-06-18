"""Tests for the Alpaca News REST adapter — all mocked, no real API hits."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from trader.adapters.alpaca.news import fetch_alpaca_news


def _fake_news(headline: str, when: datetime, source: str = "Benzinga") -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        headline=headline,
        summary="some summary",
        source=source,
        url="https://x",
        symbols=["QQQ"],
        created_at=when,
        author="",
        content=None,
        images=None,
    )


class _FakeResp:
    def __init__(self, items):
        self.news = items


def test_fetch_alpaca_news_happy_path(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "x")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "y")
    from trader import config

    config.get_settings.cache_clear()

    items = [
        _fake_news("Headline A", datetime(2026, 5, 18, 10, 0, tzinfo=UTC)),
        _fake_news("Headline B", datetime(2026, 5, 18, 12, 0, tzinfo=UTC)),
    ]
    with patch("alpaca.data.historical.news.NewsClient") as mock_client:
        mock_client.return_value.get_news.return_value = _FakeResp(items)
        out = fetch_alpaca_news(["QQQ", "SPY"])
    assert len(out) == 2
    # Sorted oldest first
    assert out[0].headline == "Headline A"
    assert out[1].headline == "Headline B"
    assert out[0].source == "Benzinga"


def test_fetch_alpaca_news_dedup_duplicate_headlines(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "x")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "y")
    from trader import config

    config.get_settings.cache_clear()

    items = [
        _fake_news("Same story", datetime(2026, 5, 18, 10, 0, tzinfo=UTC)),
        _fake_news("Same story", datetime(2026, 5, 18, 11, 0, tzinfo=UTC)),
    ]
    with patch("alpaca.data.historical.news.NewsClient") as mock_client:
        mock_client.return_value.get_news.return_value = _FakeResp(items)
        out = fetch_alpaca_news(["QQQ"])
    assert len(out) == 1


def test_fetch_alpaca_news_swallows_exceptions(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "x")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "y")
    from trader import config

    config.get_settings.cache_clear()

    with patch("alpaca.data.historical.news.NewsClient") as mock_client:
        mock_client.return_value.get_news.side_effect = RuntimeError("network")
        out = fetch_alpaca_news(["QQQ"])
    assert out == []


def test_fetch_alpaca_news_handles_naive_datetimes(monkeypatch):
    """Some clients return tz-naive datetimes — we must coerce to UTC."""
    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "x")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "y")
    from trader import config

    config.get_settings.cache_clear()

    naive = datetime(2026, 5, 18, 10, 0)  # no tz
    items = [_fake_news("Naive date", naive)]
    with patch("alpaca.data.historical.news.NewsClient") as mock_client:
        mock_client.return_value.get_news.return_value = _FakeResp(items)
        out = fetch_alpaca_news(["QQQ"])
    assert len(out) == 1
    assert out[0].published_at.tzinfo is not None


def test_fetch_alpaca_news_skips_empty_headlines(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "x")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "y")
    from trader import config

    config.get_settings.cache_clear()

    items = [
        _fake_news("", datetime(2026, 5, 18, 10, 0, tzinfo=UTC)),
        _fake_news("Valid", datetime(2026, 5, 18, 11, 0, tzinfo=UTC)),
    ]
    with patch("alpaca.data.historical.news.NewsClient") as mock_client:
        mock_client.return_value.get_news.return_value = _FakeResp(items)
        out = fetch_alpaca_news(["QQQ"])
    assert len(out) == 1
    assert out[0].headline == "Valid"
