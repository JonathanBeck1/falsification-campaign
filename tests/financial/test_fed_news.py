"""Tests for the Fed monetary-policy RSS adapter — fully mocked."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from trader.adapters.macro.fed import _parse_rss, fetch_fed_press


def _make_rss(items: list[dict]) -> str:
    item_xml = "\n".join(
        f"""    <item>
      <title>{i["title"]}</title>
      <pubDate>{i["date"]}</pubDate>
      <description>{i.get("desc", "")}</description>
    </item>"""
        for i in items
    )
    return f"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Federal Reserve Press Releases</title>
{item_xml}
  </channel>
</rss>
"""


def test_parse_rss_happy_path():
    xml = _make_rss(
        [
            {"title": "FOMC holds rates steady", "date": "Wed, 18 May 2026 14:00:00 GMT"},
            {"title": "Speech on monetary policy", "date": "Mon, 16 May 2026 09:00:00 GMT"},
        ]
    )
    items = _parse_rss(xml)
    assert len(items) == 2
    assert "Federal Reserve" in items[0].headline
    assert items[0].source == "federalreserve.gov"


def test_parse_rss_malformed_xml():
    assert _parse_rss("not xml") == []


def test_parse_rss_skips_invalid_dates():
    xml = _make_rss(
        [
            {"title": "Bad date", "date": "not a date"},
            {"title": "Good date", "date": "Wed, 18 May 2026 14:00:00 GMT"},
        ]
    )
    items = _parse_rss(xml)
    assert len(items) == 1
    assert "Good date" in items[0].headline


def test_parse_rss_skips_empty_title():
    xml = _make_rss(
        [
            {"title": "", "date": "Wed, 18 May 2026 14:00:00 GMT"},
        ]
    )
    assert _parse_rss(xml) == []


def _mock_response(text: str):
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_fed_press_happy_path():
    xml = _make_rss([{"title": "Fed news today", "date": "Wed, 18 May 2026 14:00:00 GMT"}])
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response(xml)
        items = fetch_fed_press()
    assert len(items) == 1
    assert "Fed news today" in items[0].headline


def test_fetch_fed_press_lookback_filters_old_entries():
    """lookback_days should filter out entries older than the window."""
    recent = (datetime.now(UTC) - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    old = (datetime.now(UTC) - timedelta(days=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = _make_rss(
        [
            {"title": "Recent", "date": recent},
            {"title": "Old", "date": old},
        ]
    )
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _mock_response(xml)
        items = fetch_fed_press(lookback_days=7)
    assert len(items) == 1
    assert "Recent" in items[0].headline


def test_fetch_fed_press_swallows_errors():
    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = RuntimeError("network down")
        items = fetch_fed_press()
    assert items == []
