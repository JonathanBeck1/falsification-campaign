"""Event identity must be independent of the *query set* used to fetch it.

Yahoo and Alpaca News fetch headlines under a list of context tickers. The
same story queried under different ticker lists (e.g. ["QQQ","SPY"] vs
["QQQ","SPY","IWM"]) must dedup to one event_id, otherwise news_events
accumulates duplicates as `context_tickers` evolves over time (e.g. when
the spider adds new sources or a config is updated).

Ticker attribution belongs in `entities` / `index_exposure`, not in the
event_id hash. Other normalizers (fed, sec, finnhub, web) already do this
correctly — they hash by a per-row stable identifier (URL, ticker primary,
host) rather than the caller's query set.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.alpaca_news import alpaca_news_to_events
from trader.normalization.yahoo import yahoo_news_to_events
from trader.storage.snapshot import NewsItem


def _item(headline: str) -> NewsItem:
    return NewsItem(
        headline=headline,
        source="x",
        published_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
    )


def test_yahoo_event_id_stable_across_queried_tickers():
    item = _item("S&P 500 rallies on Fed pivot")
    a = yahoo_news_to_events([item], queried_tickers=["QQQ", "SPY"])[0]
    b = yahoo_news_to_events([item], queried_tickers=["QQQ", "SPY", "IWM"])[0]
    assert a.event_id == b.event_id


def test_yahoo_event_id_stable_when_ticker_order_differs():
    item = _item("Nasdaq closes at record")
    a = yahoo_news_to_events([item], queried_tickers=["SPY", "QQQ"])[0]
    b = yahoo_news_to_events([item], queried_tickers=["QQQ", "SPY"])[0]
    assert a.event_id == b.event_id


def test_yahoo_event_id_differs_when_headline_differs():
    a = yahoo_news_to_events([_item("Story A")], queried_tickers=["SPY"])[0]
    b = yahoo_news_to_events([_item("Story B")], queried_tickers=["SPY"])[0]
    assert a.event_id != b.event_id


def test_alpaca_news_event_id_stable_across_queried_symbols():
    item = _item("Apple beats estimates on iPhone sales")
    a = alpaca_news_to_events([item], queried_symbols=["AAPL"])[0]
    b = alpaca_news_to_events([item], queried_symbols=["AAPL", "MSFT"])[0]
    assert a.event_id == b.event_id


def test_alpaca_news_event_id_differs_when_headline_differs():
    a = alpaca_news_to_events([_item("Headline A")], queried_symbols=["AAPL"])[0]
    b = alpaca_news_to_events([_item("Headline B")], queried_symbols=["AAPL"])[0]
    assert a.event_id != b.event_id
