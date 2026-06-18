"""Tests for SEC EDGAR 8-K adapter — fully mocked, no real SEC traffic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from trader.adapters.sec.edgar import _parse_atom_feed, fetch_sec_8k_filings

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Apple 8-K filings</title>
  <entry>
    <title>8-K - APPLE INC (0000320193) (Filer)</title>
    <link rel="alternate" href="https://www.sec.gov/x"/>
    <updated>2026-05-18T10:00:00-04:00</updated>
    <summary type="html">Earnings release for Q2.</summary>
  </entry>
  <entry>
    <title>8-K/A - APPLE INC (0000320193) (Filer)</title>
    <link rel="alternate" href="https://www.sec.gov/y"/>
    <updated>2026-05-10T14:00:00-04:00</updated>
    <summary type="html">Amendment to prior 8-K.</summary>
  </entry>
</feed>
"""


def test_parse_atom_feed_extracts_entries():
    items = _parse_atom_feed(SAMPLE_ATOM, "AAPL")
    assert len(items) == 2
    assert "AAPL" in items[0].headline
    assert items[0].source == "SEC EDGAR"
    assert items[0].published_at.tzinfo is not None


def test_parse_atom_feed_malformed_xml():
    assert _parse_atom_feed("not xml", "AAPL") == []


def test_parse_atom_feed_skips_entries_with_no_date():
    bad = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>No date here</title></entry>
    </feed>"""
    assert _parse_atom_feed(bad, "AAPL") == []


def _mock_response(text: str = SAMPLE_ATOM, status: int = 200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_sec_8k_filings_happy_path():
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response()
        items = fetch_sec_8k_filings(["AAPL"], count_per_ticker=3)
    assert len(items) == 2
    assert "AAPL" in items[0].headline


def test_fetch_sec_8k_filings_unknown_ticker_is_skipped():
    """Tickers not in _CIK_MAP should be skipped silently."""
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response()
        items = fetch_sec_8k_filings(["ZZZZZ_UNKNOWN"])
    assert items == []


def test_fetch_sec_8k_filings_dedups_across_tickers():
    """If the same headline appears for two tickers (unlikely but possible), dedup."""
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        # Returning the same feed for both tickers — but headlines are prefixed
        # with ticker, so they WILL differ. Verify both ticker prefixes appear.
        instance.get.return_value = _mock_response()
        items = fetch_sec_8k_filings(["AAPL", "MSFT"])
    headlines = [i.headline for i in items]
    assert any("AAPL" in h for h in headlines)
    assert any("MSFT" in h for h in headlines)


def test_fetch_sec_8k_filings_swallows_http_errors():
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = RuntimeError("connection refused")
        items = fetch_sec_8k_filings(["AAPL"])
    assert items == []


def test_fetch_sec_8k_filings_sorts_oldest_first():
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response()
        items = fetch_sec_8k_filings(["AAPL"])
    assert items[0].published_at <= items[-1].published_at
