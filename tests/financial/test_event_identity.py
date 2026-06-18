"""Tests for deterministic normalized Event identity."""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.alpaca_news import alpaca_news_to_events
from trader.normalization.finnhub import finnhub_news_to_events
from trader.normalization.sec import sec_news_to_events
from trader.normalization.yahoo import yahoo_news_to_events
from trader.storage.snapshot import NewsItem


def _item(headline: str, summary: str = "", source: str = "wire", hour: int = 12) -> NewsItem:
    return NewsItem(
        headline=headline,
        summary=summary,
        source=source,
        published_at=datetime(2026, 5, 18, hour, 0, tzinfo=UTC),
    )


def test_finnhub_event_ids_are_deterministic_for_same_item_and_ticker():
    item = _item("AAPL beats Q2 estimates", "Strong iPhone sales drove the beat.")

    first = finnhub_news_to_events([item], ticker="AAPL")[0]
    second = finnhub_news_to_events([item], ticker="AAPL")[0]

    assert first.event_id == second.event_id


def test_finnhub_event_ids_change_when_context_ticker_changes():
    item = _item("Large supplier beats Q2 estimates")

    first = finnhub_news_to_events([item], ticker="AAPL")[0]
    second = finnhub_news_to_events([item], ticker="MSFT")[0]

    assert first.event_id != second.event_id


def test_yahoo_event_ids_are_deterministic_for_same_item_and_query_set():
    item = _item("Markets close mixed")

    first = yahoo_news_to_events([item], queried_tickers=["QQQ", "SPY"])[0]
    second = yahoo_news_to_events([item], queried_tickers=["QQQ", "SPY"])[0]

    assert first.event_id == second.event_id


def test_yahoo_event_ids_ignore_query_order():
    item = _item("Markets close mixed")

    first = yahoo_news_to_events([item], queried_tickers=["QQQ", "SPY"])[0]
    second = yahoo_news_to_events([item], queried_tickers=["SPY", "QQQ"])[0]

    assert first.event_id == second.event_id


def test_alpaca_event_ids_are_deterministic_for_same_item_and_symbols():
    item = _item("Apple raises guidance for Q3", "Strong outlook on services revenue.")

    first = alpaca_news_to_events([item], queried_symbols=["AAPL"])[0]
    second = alpaca_news_to_events([item], queried_symbols=["AAPL"])[0]

    assert first.event_id == second.event_id


def test_sec_event_ids_are_deterministic_for_same_filing():
    item = _item("[SEC 8-K] MSFT: Results of Operations Q4 2026", "Earnings release.")

    first = sec_news_to_events([item])[0]
    second = sec_news_to_events([item])[0]

    assert first.event_id == second.event_id
