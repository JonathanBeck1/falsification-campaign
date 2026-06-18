"""SentimentMomentumBrain variant tests — credibility floor + dial behavior.

Pins that:
- Conservative filters out low-credibility events via credibility_floor.
- Aggressive accepts all credibility levels (floor=0.0).
- Factory helpers wire the expected dial values.
- credibility_floor out of [0, 1] is rejected at construction time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trader.normalization.models import Entity, Event
from trader.signals.sentiment_momentum import (
    SentimentMomentumBrain,
    sentiment_momentum_aggressive,
    sentiment_momentum_conservative,
)
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot
from trader.storage.store import Store


def _snapshot(
    ticker: str = "QQQ",
    price: float = 100.5,
    sma_200: float | None = 95.0,
    now: datetime | None = None,
) -> DailySnapshot:
    now = now or datetime.now(UTC)
    bar = Bar(
        timestamp=now,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=1,
    )
    return DailySnapshot(
        snapshot_id="snap",
        trade_date=now.date(),
        ticker=ticker,
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=price,
        sma_200=sma_200,
        rsi_14=55.0,
        realized_vol_20d=0.15,
        news=[],
        macro=MacroSnapshot(),
    )


def _event(
    *,
    event_id: str,
    sentiment_score: float,
    source_credibility: float = 0.8,
    published_at: datetime | None = None,
    urgency: str = "high",
) -> Event:
    """Build an event observed 1h before the default snapshot time.

    Using `observed_at = now - 1h` (rather than `now`) avoids a SQLite
    second-precision ordering issue: the brain queries
    `datetime(observed_at) < datetime(snapshot_time + 1µs)`, and at
    second precision strict `<` excludes equal-second rows.
    """
    now = datetime.now(UTC)
    observed = published_at or now - timedelta(hours=1)
    return Event(
        event_id=event_id,
        source="x_test",
        source_url="",
        title="t",
        summary="",
        published_at=observed,
        observed_at=observed,
        ingested_at=observed,
        classified_at=observed,
        entities=[Entity(name="QQQ", ticker="QQQ", confidence=1.0, role="primary")],
        asset_scope=["macro"],
        index_exposure=["QQQ"],
        event_type="macro_surprise",
        sentiment="positive" if sentiment_score > 0 else "negative" if sentiment_score < 0 else "neutral",
        sentiment_score=sentiment_score,
        urgency=urgency,
        novelty_score=0.7,
        source_credibility=source_credibility,
        evidence=[],
        model_outputs=[],
        raw_artifact_path="",
    )


def _seed_events(store: Store, events: list[Event]) -> None:
    for ev in events:
        store.save_news_event(ev)


# ── Credibility floor filtering ─────────────────────────────────────────────


def test_conservative_filters_out_low_credibility_events(tmp_path):
    """Conservative credibility_floor=0.7 should drop events with cred < 0.7,
    forcing HOLD (insufficient events) even with strong sentiment."""
    store = Store(tmp_path / "trader.sqlite")
    # 6 strongly bullish but low-credibility events — Conservative needs 5
    # with cred >= 0.7. All have 0.5 cred, so all are dropped.
    _seed_events(
        store,
        [_event(event_id=f"e{i}", sentiment_score=0.9, source_credibility=0.5) for i in range(6)],
    )
    brain = sentiment_momentum_conservative(store=store)
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "insufficient" in decision.reasoning


def test_aggressive_accepts_low_credibility_events(tmp_path):
    """Aggressive credibility_floor=0.0 keeps every event regardless of cred."""
    store = Store(tmp_path / "trader.sqlite")
    _seed_events(
        store,
        [_event(event_id=f"e{i}", sentiment_score=0.9, source_credibility=0.2) for i in range(3)],
    )
    brain = sentiment_momentum_aggressive(store=store)
    decision = brain.decide(_snapshot())
    # Aggressive min_events=2 + low buy_threshold=0.10 → BUY
    assert decision.action == "BUY"


def test_credibility_floor_at_exact_boundary_accepts(tmp_path):
    """An event with credibility == floor should pass (>= comparison)."""
    store = Store(tmp_path / "trader.sqlite")
    _seed_events(
        store,
        [_event(event_id=f"e{i}", sentiment_score=0.9, source_credibility=0.7) for i in range(5)],
    )
    brain = sentiment_momentum_conservative(store=store)
    decision = brain.decide(_snapshot())
    assert decision.action == "BUY"


# ── Lookback window dial ────────────────────────────────────────────────────


def test_conservative_uses_shorter_lookback(tmp_path):
    """Conservative lookback_hours=24 — events older than 24h must be ignored."""
    store = Store(tmp_path / "trader.sqlite")
    now = datetime.now(UTC)
    # 5 high-cred events from 30+ hours ago — outside the 24h window.
    _seed_events(
        store,
        [
            _event(
                event_id=f"e{i}",
                sentiment_score=0.9,
                source_credibility=0.9,
                published_at=now - timedelta(hours=30),
            )
            for i in range(5)
        ],
    )
    brain = sentiment_momentum_conservative(store=store)
    decision = brain.decide(_snapshot(now=now))
    assert decision.action == "HOLD"


def test_aggressive_uses_longer_lookback(tmp_path):
    """Aggressive lookback_hours=72 — 30h-old events still count."""
    store = Store(tmp_path / "trader.sqlite")
    now = datetime.now(UTC)
    _seed_events(
        store,
        [
            _event(
                event_id=f"e{i}",
                sentiment_score=0.9,
                source_credibility=0.9,
                published_at=now - timedelta(hours=30),
            )
            for i in range(3)
        ],
    )
    brain = sentiment_momentum_aggressive(store=store)
    decision = brain.decide(_snapshot(now=now))
    assert decision.action == "BUY"


# ── Factory dial values ─────────────────────────────────────────────────────


def test_sentiment_momentum_conservative_factory_values(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    brain = sentiment_momentum_conservative(store=store, name="X")
    assert brain.name == "X"
    assert brain._lookback_hours == 24
    assert brain._recency_half_life_hours == 4.0
    assert brain._buy_threshold == 0.30
    assert brain._sell_threshold == -0.30
    assert brain._min_events_for_signal == 5
    assert brain._credibility_floor == 0.7


def test_sentiment_momentum_aggressive_factory_values(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    brain = sentiment_momentum_aggressive(store=store, name="Y")
    assert brain.name == "Y"
    assert brain._lookback_hours == 72
    assert brain._recency_half_life_hours == 12.0
    assert brain._buy_threshold == 0.10
    assert brain._sell_threshold == -0.10
    assert brain._min_events_for_signal == 2
    assert brain._credibility_floor == 0.0


# ── Constructor validation ──────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [-0.1, 1.1, -5.0, 5.0])
def test_credibility_floor_out_of_range_rejected(bad: float, tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    with pytest.raises(ValueError, match="credibility_floor"):
        SentimentMomentumBrain(store=store, credibility_floor=bad)


def test_default_credibility_floor_is_zero(tmp_path):
    """Backward-compat: default constructor accepts all credibility levels."""
    store = Store(tmp_path / "trader.sqlite")
    brain = SentimentMomentumBrain(store=store)
    assert brain._credibility_floor == 0.0
