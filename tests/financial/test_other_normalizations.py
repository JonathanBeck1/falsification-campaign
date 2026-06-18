"""Tests for finnhub / yahoo / alpaca_news / sec normalizers."""

from __future__ import annotations

from datetime import UTC, datetime

from trader.normalization.alpaca_news import alpaca_news_to_events
from trader.normalization.finnhub import (
    classify_event_type as finnhub_classify_event_type,
)
from trader.normalization.finnhub import (
    classify_urgency as finnhub_classify_urgency,
)
from trader.normalization.finnhub import (
    finnhub_news_to_events,
)
from trader.normalization.sec import (
    _parse_headline,
    sec_news_to_events,
)
from trader.normalization.sec import (
    classify_event_type as sec_classify_event_type,
)
from trader.normalization.sec import (
    classify_urgency as sec_classify_urgency,
)
from trader.normalization.yahoo import yahoo_news_to_events
from trader.storage.snapshot import NewsItem


def _item(headline: str, summary: str = "", source: str = "x", hour: int = 12) -> NewsItem:
    return NewsItem(
        headline=headline,
        summary=summary,
        source=source,
        published_at=datetime(2026, 5, 18, hour, 0, tzinfo=UTC),
    )


# ── Finnhub ───────────────────────────────────────────────────────────────────


def test_finnhub_classify_event_type_earnings():
    assert finnhub_classify_event_type("Apple tops estimates on Q2 earnings") == "earnings_surprise"


def test_finnhub_classify_event_type_mna():
    assert finnhub_classify_event_type("MegaCorp acquires SmallCo for $4B") == "mna"


def test_finnhub_classify_event_type_default_other():
    assert finnhub_classify_event_type("Apple stock moves on Tuesday") == "other"


def test_finnhub_classify_urgency_breaking():
    assert finnhub_classify_urgency("BREAKING: trading halted on AAPL") == "high"


def test_finnhub_news_to_events_attaches_primary_entity():
    items = [_item("AAPL beats Q2 estimates", "Strong iPhone sales drove the beat.")]
    events = finnhub_news_to_events(items, ticker="AAPL")
    assert len(events) == 1
    e = events[0]
    assert e.source == "finnhub"
    assert e.event_type == "earnings_surprise"
    assert len(e.entities) == 1
    assert e.entities[0].ticker == "AAPL"
    assert e.entities[0].confidence >= 0.9
    assert e.entities[0].role == "primary"


def test_finnhub_news_to_events_index_ticker_adds_macro_scope():
    items = [_item("SPY moves on Fed news")]
    events = finnhub_news_to_events(items, ticker="SPY")
    assert "index" in events[0].asset_scope
    assert events[0].index_exposure == ["SPY", "QQQ"]


# ── Yahoo ─────────────────────────────────────────────────────────────────────


def test_yahoo_news_to_events_marks_index_queries_macro():
    items = [_item("Markets close mixed")]
    events = yahoo_news_to_events(items, queried_tickers=["QQQ", "SPY"])
    e = events[0]
    assert "macro" in e.asset_scope
    assert e.index_exposure == ["QQQ", "SPY"]
    assert all(ent.role == "mentioned" for ent in e.entities)
    assert all(0.4 <= ent.confidence <= 0.7 for ent in e.entities)


def test_yahoo_news_to_events_single_name_scope():
    items = [_item("Nvidia announces new chip")]
    events = yahoo_news_to_events(items, queried_tickers=["NVDA"])
    assert events[0].asset_scope == ["single_name"]
    assert events[0].index_exposure == []


def test_yahoo_news_to_events_classifies_fed_commentary():
    items = [_item("Former Fed Official: The Fed's Biggest Mistake Was Keeping Rates Low Too Long")]
    events = yahoo_news_to_events(items, queried_tickers=["SPY", "QQQ"])
    assert events[0].event_type == "fed_commentary"
    assert events[0].urgency == "high"


def test_yahoo_news_to_events_classifies_earnings_and_product_launch():
    items = [
        _item("What Nvidia Earnings Mean for VOO and QQQ"),
        _item("Nvidia announces new AI chip for data centers"),
    ]
    events = yahoo_news_to_events(items, queried_tickers=["NVDA", "QQQ"])
    assert [event.event_type for event in events] == ["earnings_surprise", "product_launch"]


def test_yahoo_news_to_events_classifies_analyst_language():
    """Analyst-upgrade phrasing classifies. The earlier version of this test
    also asserted that "Consider Your Options" → unusual_social_velocity,
    which was a substring-match false positive — the phrase is generic
    English, not derivative/social activity. See `test_yahoo_classifier_adversarial.py`
    for the new boundaries."""
    items = [
        _item("Analyst upgrades AMD after strong AI demand"),
        _item("Be Cautious With AMD at $420 and Consider Your Options"),
    ]
    events = yahoo_news_to_events(items, queried_tickers=["AMD"])
    assert events[0].event_type == "analyst_upgrade"
    # The second headline is generic commentary — no longer flagged as
    # social-velocity. Real unusual-options would say "unusual options flow"
    # or name a specific derivative phenomenon.
    assert events[1].event_type != "unusual_social_velocity"


def test_yahoo_news_to_events_uses_summary_for_classification():
    items = [_item("Retail Returns, Momo Retreats", summary="Stocks retreat after inflation data rattles investors")]
    events = yahoo_news_to_events(items, queried_tickers=["SPY"])
    assert events[0].event_type == "macro_surprise"


# ── Alpaca News (Benzinga) ────────────────────────────────────────────────────


def test_alpaca_news_to_events_attaches_symbols():
    items = [_item("Apple raises guidance for Q3", "Strong outlook on services revenue.")]
    events = alpaca_news_to_events(items, queried_symbols=["AAPL"])
    e = events[0]
    assert e.source == "alpaca_news"
    assert e.event_type == "guidance_raise"
    assert e.entities[0].ticker == "AAPL"
    assert e.source_credibility >= 0.8


def test_alpaca_news_to_events_empty_input():
    assert alpaca_news_to_events([], queried_symbols=["AAPL"]) == []


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────


def test_sec_parse_headline_with_prefix():
    ticker, title = _parse_headline("[SEC 8-K] AAPL: Results of Operations Q3 2026")
    assert ticker == "AAPL"
    assert title == "Results of Operations Q3 2026"


def test_sec_parse_headline_without_prefix():
    ticker, title = _parse_headline("Some other headline")
    assert ticker is None
    assert title == "Some other headline"


def test_sec_classify_event_type_earnings():
    assert sec_classify_event_type("Item 2.02 Results of Operations") == "earnings_surprise"


def test_sec_classify_event_type_mna():
    assert sec_classify_event_type("Material Definitive Agreement for Acquisition") == "mna"


def test_sec_classify_event_type_default():
    assert sec_classify_event_type("Other Events") == "regulatory_action"


def test_sec_classify_urgency_breaking():
    assert sec_classify_urgency("Notice of Bankruptcy Filing") == "breaking"


def test_sec_news_to_events_extracts_ticker_from_prefix():
    items = [_item("[SEC 8-K] MSFT: Results of Operations Q4 2026", "Earnings release.")]
    events = sec_news_to_events(items)
    e = events[0]
    assert e.source == "sec_edgar"
    assert e.title == "Results of Operations Q4 2026"
    assert e.entities[0].ticker == "MSFT"
    assert e.entities[0].confidence >= 0.95
    assert e.entities[0].role == "primary"
    assert e.event_type == "earnings_surprise"
    assert e.source_credibility == 1.0


def test_sec_news_to_events_handles_missing_prefix_gracefully():
    items = [_item("Some unparseable filing headline")]
    events = sec_news_to_events(items)
    e = events[0]
    assert e.entities == []
    assert e.title == "Some unparseable filing headline"
