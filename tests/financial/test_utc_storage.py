from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trader.adapters.sec.edgar import _parse_atom_feed
from trader.normalization.models import Event
from trader.normalization.sec import sec_news_to_events
from trader.storage.store import Store
from trader.storage.utc import ensure_utc, to_iso_z


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(event_id: str, published_at: datetime) -> Event:
    return Event(
        event_id=event_id,
        source="test",
        title=event_id,
        published_at=published_at,
        observed_at=published_at,
        ingested_at=published_at,
        classified_at=published_at,
    )


def test_ensure_utc_assumes_naive_inputs_are_utc():
    out = ensure_utc(datetime(2026, 5, 20, 12, 0))

    assert out == datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def test_ensure_utc_converts_offset_aware_inputs():
    out = ensure_utc(_dt("2026-05-20T08:00:00-04:00"))

    assert out == datetime(2026, 5, 20, 12, 0, tzinfo=UTC)


def test_ensure_utc_rejects_none():
    with pytest.raises(ValueError):
        ensure_utc(None)  # type: ignore[arg-type]


def test_news_event_since_filter_orders_mixed_offsets_by_utc_instant(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    noon_utc = _event("evt_noon_offset", _dt("2026-05-20T08:00:00-04:00"))
    eleven_utc = _event("evt_eleven_z", _dt("2026-05-20T11:00:00Z"))
    store.save_news_event(noon_utc)
    store.save_news_event(eleven_utc)
    with sqlite3.connect(tmp_path / "trader.sqlite") as conn:
        conn.execute(
            "UPDATE news_events SET published_at = ? WHERE event_id = ?",
            ("2026-05-20T08:00:00-04:00", "evt_noon_offset"),
        )
        conn.execute(
            "UPDATE news_events SET published_at = ? WHERE event_id = ?",
            ("2026-05-20T11:00:00+00:00", "evt_eleven_z"),
        )

    # The cutoff is between 11:00Z and 12:00Z; only the offset-authored noon
    # event should survive even if older rows still contain mixed-offset text.
    rows = store.get_news_events(since=_dt("2026-05-20T11:30:00Z"))

    assert [row["event_id"] for row in rows] == ["evt_noon_offset"]


def test_news_event_write_storage_canonicalizes_offset_timestamp(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_news_event(_event("evt_offset", _dt("2026-05-20T08:00:00-04:00")))

    with sqlite3.connect(tmp_path / "trader.sqlite") as conn:
        stored = conn.execute("SELECT published_at FROM news_events WHERE event_id = ?", ("evt_offset",)).fetchone()[0]

    assert stored == "2026-05-20T12:00:00.000000+00:00"


def test_sec_edgar_path_stores_feed_offsets_as_utc(tmp_path: Path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>8-K - APPLE INC (0000320193) (Filer)</title>
        <updated>2026-05-20T08:00:00-04:00</updated>
        <summary type="html">Earnings release.</summary>
      </entry>
    </feed>
    """
    store = Store(tmp_path / "trader.sqlite")
    [event] = sec_news_to_events(_parse_atom_feed(xml, "AAPL"), observed_at=_dt("2026-05-20T13:00:00Z"))
    store.save_news_event(event)

    with sqlite3.connect(tmp_path / "trader.sqlite") as conn:
        stored = conn.execute("SELECT published_at FROM news_events WHERE event_id = ?", (event.event_id,)).fetchone()[0]

    assert stored == to_iso_z(_dt("2026-05-20T12:00:00Z"))
