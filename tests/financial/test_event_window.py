"""Tests for the event-window research harness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trader.backtesting.event_window import (
    HorizonStats,
    WindowResult,
    _price_at_or_after,
    aggregate_by_type,
    compute_event_returns,
    format_report,
)
from trader.normalization.fed import fed_news_to_events
from trader.normalization.models import Event
from trader.storage.snapshot import Bar, NewsItem
from trader.storage.store import Store


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(timestamp=ts, open=close, high=close, low=close, close=close, volume=1_000)


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 18, hour, minute, tzinfo=UTC)


# ── _price_at_or_after ───────────────────────────────────────────────────────


def test_price_at_or_after_empty_bars():
    assert _price_at_or_after([], _ts(10)) is None


def test_price_at_or_after_exact_timestamp():
    bars = [_bar(_ts(10), 100), _bar(_ts(11), 101)]
    assert _price_at_or_after(bars, _ts(10)) == 100
    assert _price_at_or_after(bars, _ts(11)) == 101


def test_price_at_or_after_between_bars_returns_next():
    bars = [_bar(_ts(10), 100), _bar(_ts(11), 101)]
    # 10:30 falls between bars -> next available is 11:00 (101)
    assert _price_at_or_after(bars, _ts(10, 30)) == 101


def test_price_at_or_after_before_first_bar_returns_first():
    bars = [_bar(_ts(10), 100), _bar(_ts(11), 101)]
    assert _price_at_or_after(bars, _ts(9)) == 100


def test_price_at_or_after_past_last_bar_returns_none():
    bars = [_bar(_ts(10), 100)]
    assert _price_at_or_after(bars, _ts(11)) is None


# ── compute_event_returns ────────────────────────────────────────────────────


def _event(
    published_at: datetime,
    etype: str = "fed_commentary",
    observed_at: datetime | None = None,
    ingested_at: datetime | None = None,
    classified_at: datetime | None = None,
) -> Event:
    event = fed_news_to_events(
        [NewsItem(headline=f"Event @ {published_at}", summary="", source="test", published_at=published_at)]
    )[0]
    observed_at = observed_at or published_at
    ingested_at = ingested_at or observed_at
    classified_at = classified_at or observed_at
    return event.model_copy(
        update={
            "event_type": etype,
            "observed_at": observed_at,
            "ingested_at": ingested_at,
            "classified_at": classified_at,
        }
    )


def test_compute_event_returns_happy_path():
    bars = [
        _bar(_ts(14, 0), 100.0),  # event price
        _bar(_ts(14, 5), 100.5),  # +5m → +0.5%
        _bar(_ts(14, 15), 101.0),  # +15m → +1.0%
        _bar(_ts(14, 30), 99.5),  # +30m → -0.5%
        _bar(_ts(15, 0), 102.0),  # +1h → +2.0%
        _bar(_ts(18, 0), 103.0),  # +4h → +3.0%
    ]
    events = [_event(_ts(14, 0))]
    results = compute_event_returns(
        events,
        bars,
        benchmark="SPY",
        horizons={
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
        },
    )
    assert len(results) == 5
    by_h = {r.horizon: r for r in results}
    assert by_h["5m"].return_pct == 0.5
    assert by_h["15m"].return_pct == 1.0
    assert by_h["30m"].return_pct == -0.5
    assert by_h["1h"].return_pct == 2.0
    assert by_h["4h"].return_pct == 3.0


def test_compute_event_returns_skips_events_past_last_bar():
    """If event timestamp is after the last available bar, nothing is produced."""
    bars = [_bar(_ts(14, 0), 100.0)]
    events = [_event(_ts(14, 0) + timedelta(hours=1))]
    results = compute_event_returns(
        events,
        bars,
        horizons={"5m": timedelta(minutes=5), "1d": timedelta(days=1)},
    )
    assert results == []


def test_compute_event_returns_skips_horizons_past_last_bar():
    """Event has a price, but horizons past the last bar are skipped."""
    bars = [_bar(_ts(14, 0), 100.0), _bar(_ts(14, 5), 101.0)]
    events = [_event(_ts(14, 0))]
    results = compute_event_returns(
        events,
        bars,
        horizons={"5m": timedelta(minutes=5), "1h": timedelta(hours=1)},
    )
    # 5m hits the second bar; 1h has no coverage.
    assert len(results) == 1
    assert results[0].horizon == "5m"


def test_compute_event_returns_default_horizons_used_when_none_passed():
    bars = [_bar(_ts(14, 0) + timedelta(minutes=i), 100 + i * 0.01) for i in range(0, 360, 5)]
    events = [_event(_ts(14, 0))]
    results = compute_event_returns(events, bars)
    # Should produce one result per horizon that has data; at least 5m/15m/30m/1h.
    horizons_used = {r.horizon for r in results}
    assert {"5m", "15m", "30m", "1h"}.issubset(horizons_used)


def test_compute_event_returns_zero_event_price_is_skipped():
    bars = [_bar(_ts(14, 0), 0.0), _bar(_ts(14, 5), 1.0)]
    events = [_event(_ts(14, 0))]
    results = compute_event_returns(events, bars, horizons={"5m": timedelta(minutes=5)})
    assert results == []


def test_compute_event_returns_anchors_to_observed_at_not_published_at():
    published_at = _ts(13, 0)
    observed_at = _ts(14, 0)
    bars = [
        _bar(_ts(13, 0), 50.0),
        _bar(_ts(13, 5), 55.0),
        _bar(_ts(14, 0), 100.0),
        _bar(_ts(14, 5), 101.0),
    ]
    events = [_event(published_at, observed_at=observed_at)]

    results = compute_event_returns(events, bars, horizons={"5m": timedelta(minutes=5)})

    assert len(results) == 1
    assert results[0].observed_at == observed_at
    assert results[0].price_at_event == 100.0
    assert results[0].return_pct == 1.0


# ── aggregate_by_type ────────────────────────────────────────────────────────


def _wr(etype: str, horizon: str, ret_pct: float) -> WindowResult:
    return WindowResult(
        event_id="x",
        event_type=etype,
        benchmark="SPY",
        horizon=horizon,
        observed_at=_ts(14),
        price_at_event=100.0,
        price_at_horizon=100.0 * (1 + ret_pct / 100),
        return_pct=ret_pct,
    )


def test_aggregate_by_type_groups_and_counts():
    results = [
        _wr("fed_commentary", "5m", 0.5),
        _wr("fed_commentary", "5m", -0.2),
        _wr("fed_commentary", "5m", 0.1),
        _wr("earnings_surprise", "5m", 2.0),
    ]
    stats = aggregate_by_type(results)
    assert len(stats) == 2
    by_key = {(s.event_type, s.horizon): s for s in stats}
    fed_5m = by_key[("fed_commentary", "5m")]
    assert fed_5m.n == 3
    assert fed_5m.hit_rate == 2 / 3  # 2 positive out of 3
    assert fed_5m.min_return_pct == -0.2
    assert fed_5m.max_return_pct == 0.5


def test_aggregate_by_type_empty():
    assert aggregate_by_type([]) == []


def test_aggregate_by_type_single_value_has_zero_stdev():
    stats = aggregate_by_type([_wr("x", "5m", 1.0)])
    assert stats[0].stdev_return_pct == 0.0


# ── format_report ────────────────────────────────────────────────────────────


def test_format_report_produces_markdown_table():
    stats = [
        HorizonStats(
            event_type="fed_commentary",
            horizon="15m",
            n=4,
            hit_rate=0.75,
            mean_return_pct=0.30,
            median_return_pct=0.25,
            stdev_return_pct=0.15,
            min_return_pct=-0.10,
            max_return_pct=0.60,
        )
    ]
    report = format_report(stats, benchmark="SPY")
    assert "# Event-Window Study: SPY" in report
    assert "| event_type | horizon | n |" in report
    assert "fed_commentary" in report
    assert "15m" in report
    assert "75%" in report  # hit rate


def test_format_report_includes_metadata_block():
    stats = [
        HorizonStats(
            event_type="fed_commentary",
            horizon="15m",
            n=2,
            hit_rate=0.5,
            mean_return_pct=0.12,
            median_return_pct=0.12,
            stdev_return_pct=0.04,
            min_return_pct=-0.02,
            max_return_pct=0.26,
        )
    ]

    report = format_report(
        stats,
        benchmark="SPY",
        metadata={
            "events": 3,
            "bars": 500,
            "source": "federalreserve.gov",
            "event_type": "fed_commentary",
        },
    )

    assert "events: 3" in report
    assert "bars: 500" in report
    assert "source: federalreserve.gov" in report


# ── Store + Event roundtrip ──────────────────────────────────────────────────


def test_store_get_news_events_parsed_returns_event_objects(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    events_in = fed_news_to_events(
        [
            NewsItem(
                headline="FOMC Statement on Monetary Policy",
                summary="Steady.",
                source="federalreserve.gov",
                published_at=_ts(14),
            )
        ]
    )
    for e in events_in:
        store.save_news_event(e)

    parsed = store.get_news_events_parsed()
    assert len(parsed) == 1
    assert isinstance(parsed[0], Event)
    assert parsed[0].event_type == "fed_commentary"
    assert parsed[0].source == "federalreserve.gov"


def test_as_of_before_observed_at_hides_backdated_event(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    observed_at = _ts(14, 0)
    event = _event(
        published_at=observed_at - timedelta(hours=1),
        observed_at=observed_at,
        classified_at=observed_at,
    )
    store.save_news_event(event)

    visible = store.get_news_events_parsed(as_of=observed_at - timedelta(minutes=1))

    assert visible == []


def test_as_of_after_observed_at_shows_backdated_event(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    observed_at = _ts(14, 0)
    event = _event(
        published_at=observed_at - timedelta(hours=1),
        observed_at=observed_at,
        classified_at=observed_at,
    )
    store.save_news_event(event)

    visible = store.get_news_events_parsed(as_of=observed_at + timedelta(minutes=1))

    assert [e.event_id for e in visible] == [event.event_id]


def test_as_of_filters_classified_at_downstream(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    observed_at = _ts(14, 0)
    classified_at = observed_at + timedelta(minutes=5)
    event = _event(
        published_at=observed_at - timedelta(hours=1),
        observed_at=observed_at,
        classified_at=classified_at,
    )
    store.save_news_event(event)

    visible = store.get_news_events_parsed(as_of=observed_at + timedelta(minutes=1))

    assert visible == []


def test_as_of_filters_ingested_at_downstream(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    observed_at = _ts(14, 0)
    ingested_at = observed_at + timedelta(minutes=5)
    event = _event(
        published_at=observed_at - timedelta(hours=1),
        observed_at=observed_at,
        ingested_at=ingested_at,
        classified_at=observed_at,
    )
    store.save_news_event(event)

    visible = store.get_news_events_parsed(as_of=observed_at + timedelta(minutes=1))

    assert visible == []


def test_event_from_row_handles_classified_at_none(tmp_path: Path):
    """classified_at is nullable in schema; parser must not choke on null."""
    store = Store(tmp_path / "trader.sqlite")
    events = fed_news_to_events(
        [
            NewsItem(headline="x", source="x", published_at=_ts(14)),
        ]
    )
    assert isinstance(events[0].classified_at, datetime)

    store.save_news_event(events[0])
    with store._conn() as c:
        c.execute("UPDATE news_events SET classified_at = NULL WHERE event_id = ?", (events[0].event_id,))

    parsed = store.get_news_events_parsed()
    assert parsed[0].classified_at is None
