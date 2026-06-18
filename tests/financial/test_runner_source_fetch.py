"""Tests for source-fetch fault isolation."""

from __future__ import annotations

from datetime import UTC, datetime

from trader import runner
from trader.storage.snapshot import NewsItem


def _item(headline: str, source: str) -> NewsItem:
    return NewsItem(
        headline=headline,
        source=source,
        published_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
    )


def test_fetch_source_news_isolates_one_broken_provider(monkeypatch):
    def broken_finnhub(*args, **kwargs):
        raise RuntimeError("finnhub temporarily down")

    monkeypatch.setattr(runner, "fetch_news", broken_finnhub)
    monkeypatch.setattr(runner, "fetch_alpaca_news", lambda *args, **kwargs: [_item("alpaca ok", "alpaca")])
    monkeypatch.setattr(runner, "fetch_yahoo_news", lambda *args, **kwargs: [_item("yahoo ok", "yahoo")])
    monkeypatch.setattr(runner, "fetch_sec_8k_filings", lambda *args, **kwargs: [_item("sec ok", "sec")])
    monkeypatch.setattr(runner, "fetch_fed_press", lambda *args, **kwargs: [_item("fed ok", "fed")])
    monkeypatch.setattr(runner, "fetch_web_news", lambda *args, **kwargs: [_item("web ok", "marketwatch.com")])

    by_source = runner.fetch_source_news("AAPL", ["AAPL", "SPY"], ["AAPL"])

    assert by_source["finnhub"] == []
    assert [item.headline for item in by_source["alpaca_news"]] == ["alpaca ok"]
    assert [item.headline for item in by_source["yahoo_news"]] == ["yahoo ok"]
    assert [item.headline for item in by_source["sec_edgar"]] == ["sec ok"]
    assert [item.headline for item in by_source["fed"]] == ["fed ok"]
    assert [item.headline for item in by_source["web_news"]] == ["web ok"]


def test_merge_source_news_includes_web_news():
    by_source = {
        "finnhub": [_item("finnhub ok", "finnhub")],
        "alpaca_news": [],
        "sec_edgar": [],
        "fed": [],
        "yahoo_news": [],
        "web_news": [_item("web ok", "marketwatch.com")],
    }

    merged = runner._merge_source_news(by_source)

    assert [item.headline for item in merged] == ["finnhub ok", "web ok"]


def test_fetch_source_news_default_fed_lookback_is_90_days(monkeypatch):
    """Fed RSS default was 14 days, which empirically returned zero events on
    most days because the FOMC ships items every ~6 weeks. Default is now 90.
    See brain/decisions/2026-05-19-milestone-1-first-event-report.md."""
    captured: dict = {}

    def spy_fed_press(*, lookback_days, timeout=10.0):
        captured["fed_lookback_days"] = lookback_days
        return []

    monkeypatch.setattr(runner, "fetch_news", lambda *a, **kw: [])
    monkeypatch.setattr(runner, "fetch_alpaca_news", lambda *a, **kw: [])
    monkeypatch.setattr(runner, "fetch_yahoo_news", lambda *a, **kw: [])
    monkeypatch.setattr(runner, "fetch_sec_8k_filings", lambda *a, **kw: [])
    monkeypatch.setattr(runner, "fetch_fed_press", spy_fed_press)
    monkeypatch.setattr(runner, "fetch_web_news", lambda *a, **kw: [])

    runner.fetch_source_news("SPY", ["SPY"], None)
    assert captured["fed_lookback_days"] == 90


def test_fetch_source_news_lookback_days_overrides_defaults(monkeypatch):
    """--lookback-days N must apply to every adapter that supports a lookback."""
    captured: dict = {}

    def spy_finnhub(ticker, *, lookback_days, limit):
        captured["finnhub"] = lookback_days
        return []

    def spy_alpaca(tickers, *, lookback_days, limit):
        captured["alpaca_news"] = lookback_days
        return []

    def spy_fed(*, lookback_days, timeout=10.0):
        captured["fed"] = lookback_days
        return []

    def spy_web(*, lookback_days):
        captured["web_news"] = lookback_days
        return []

    monkeypatch.setattr(runner, "fetch_news", spy_finnhub)
    monkeypatch.setattr(runner, "fetch_alpaca_news", spy_alpaca)
    monkeypatch.setattr(runner, "fetch_yahoo_news", lambda *a, **kw: [])
    monkeypatch.setattr(runner, "fetch_sec_8k_filings", lambda *a, **kw: [])
    monkeypatch.setattr(runner, "fetch_fed_press", spy_fed)
    monkeypatch.setattr(runner, "fetch_web_news", spy_web)

    runner.fetch_source_news("SPY", ["SPY"], None, lookback_days=180)
    assert captured == {"finnhub": 180, "alpaca_news": 180, "fed": 180, "web_news": 180}
