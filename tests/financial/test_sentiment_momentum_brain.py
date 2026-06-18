"""SentimentMomentumBrain tests.

The brain is purely deterministic — same events + same snapshot -> same
Decision. These tests pin the relevance filter, weighting algorithm,
trend confirmation, and threshold-driven action selection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trader.normalization.models import Entity, Event
from trader.signals.sentiment_momentum import SentimentMomentumBrain
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot
from trader.storage.store import Store


def _snapshot(
    ticker: str = "QQQ",
    price: float = 100.5,
    sma_200: float | None = 95.0,
    now: datetime | None = None,
) -> DailySnapshot:
    """Trend-up snapshot by default (price > SMA200). Override sma_200 for trend-down tests."""
    now = now or datetime.now(UTC)
    bars = [
        Bar(
            timestamp=now - timedelta(hours=2 - h),
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=1,
        )
        for h in range(3)
    ]
    return DailySnapshot(
        snapshot_id="snap",
        trade_date=now.date(),
        ticker=ticker,
        latest_bar=bars[-1],
        recent_bars=bars,
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
    urgency: str = "normal",
    asset_scope: list[str] | None = None,
    index_exposure: list[str] | None = None,
    entity_tickers: list[str] | None = None,
    published_at: datetime | None = None,
    novelty_score: float = 0.7,
    source_credibility: float = 0.8,
) -> Event:
    now = datetime.now(UTC)
    published = published_at or now - timedelta(hours=1)
    return Event(
        event_id=event_id,
        source="x_test",
        source_url="",
        title="t",
        summary="",
        published_at=published,
        observed_at=published,
        ingested_at=published,
        classified_at=published,
        entities=[Entity(name=t, ticker=t, confidence=1.0, role="primary") for t in (entity_tickers or [])],
        asset_scope=asset_scope or ["macro"],
        index_exposure=index_exposure or [],
        event_type="macro_surprise",
        sentiment="positive" if sentiment_score > 0 else "negative" if sentiment_score < 0 else "neutral",
        sentiment_score=sentiment_score,
        urgency=urgency,
        novelty_score=novelty_score,
        source_credibility=source_credibility,
        evidence=[],
        model_outputs=[],
        raw_artifact_path="",
    )


def test_empty_store_returns_hold(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert decision.target_pct == 0.5
    assert "insufficient" in decision.reasoning


def test_unclassified_neutral_events_excluded_from_count(tmp_path):
    """Per Codex adversarial review (2026-05-20): events with default
    sentiment=neutral + sentiment_score=0.0 and no model_outputs are
    missing data, not signal-neutral observations. They must NOT count
    toward min_events_for_signal."""
    store = Store(tmp_path / "trader.sqlite")
    # 5 events, all default-neutral (no enrichment, score=0, label=neutral
    # via the helper since 0 maps to "neutral").
    for i in range(5):
        store.save_news_event(_event(event_id=f"evt_unclass_{i}", sentiment_score=0.0))
    brain = SentimentMomentumBrain(store=store, min_events_for_signal=3)
    decision = brain.decide(_snapshot())
    # Quorum should NOT be reached because all events are unclassified.
    assert decision.action == "HOLD"
    assert "unclassified events skipped" in decision.reasoning
    assert "5 unclassified events skipped" in decision.reasoning


def test_enriched_neutral_event_is_classified_even_when_score_zero(tmp_path):
    """An event with model_outputs set IS classified — the enricher ran
    and concluded neutral. That's a real signal-neutral observation, not
    missing data."""
    from trader.normalization.models import ModelOutputMeta

    store = Store(tmp_path / "trader.sqlite")
    # Mix: 2 bullish-enriched + 1 neutral-but-enriched + 2 default-neutral.
    for i in range(2):
        store.save_news_event(_event(event_id=f"bull_{i}", sentiment_score=0.7))
    for i in range(2):
        store.save_news_event(_event(event_id=f"unclass_{i}", sentiment_score=0.0))

    # One neutral-but-explicitly-classified event. Use
    # validation_status="auto_passed" so the new _is_classified filter
    # accepts it; default "unreviewed" would be (correctly) excluded.
    e = _event(event_id="enriched_neutral", sentiment_score=0.0)
    e = e.model_copy(
        update={
            "model_outputs": [
                ModelOutputMeta(
                    classifier="test-enricher-v1",
                    prompt_version="v0",
                    validation_status="auto_passed",
                    created_at=datetime.now(UTC),
                )
            ]
        }
    )
    store.save_news_event(e)

    brain = SentimentMomentumBrain(store=store, min_events_for_signal=3)
    decision = brain.decide(_snapshot())
    # 3 classified (2 bull + 1 enriched-neutral) >= min 3 — quorum hit.
    assert decision.action == "BUY"  # bullish wins; aggregate > buy_threshold
    assert "2 unclassified events skipped" in decision.reasoning


def test_below_min_events_returns_hold(tmp_path):
    """With fewer than min_events relevant events, the brain should not produce a directional signal."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(2):
        store.save_news_event(_event(event_id=f"evt_{i}", sentiment_score=0.8))
    brain = SentimentMomentumBrain(store=store, min_events_for_signal=3)
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"


def test_all_bullish_macro_events_with_trend_up_returns_buy_full(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    for i in range(5):
        store.save_news_event(_event(event_id=f"evt_bull_{i}", sentiment_score=0.7, urgency="high"))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot(price=100.5, sma_200=95.0))
    assert decision.action == "BUY"
    assert decision.target_pct == 1.0
    assert "aggregate_sentiment=+" in decision.reasoning
    assert "trend up" in decision.reasoning


def test_uses_snapshot_time_instead_of_wall_clock_for_lookback(tmp_path):
    """Historical replay must evaluate the event window at the snapshot time,
    not today's wall clock."""
    store = Store(tmp_path / "trader.sqlite")
    snap_time = datetime(2024, 1, 15, 13, tzinfo=UTC)
    for i in range(5):
        store.save_news_event(
            _event(
                event_id=f"evt_replay_{i}",
                sentiment_score=0.7,
                urgency="high",
                published_at=snap_time - timedelta(hours=1),
            )
        )
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot(now=snap_time))
    assert decision.action == "BUY"


def test_events_after_snapshot_time_are_not_visible(tmp_path):
    """No future leakage: events published after the snapshot decision time
    must not influence a replay decision."""
    store = Store(tmp_path / "trader.sqlite")
    snap_time = datetime.now(UTC) - timedelta(hours=2)
    for i in range(5):
        store.save_news_event(
            _event(
                event_id=f"evt_future_{i}",
                sentiment_score=0.9,
                urgency="breaking",
                published_at=snap_time + timedelta(hours=1),
            )
        )
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot(now=snap_time))
    assert decision.action == "HOLD"


def test_all_bullish_with_trend_down_returns_half_exposure(tmp_path):
    """Bullish sentiment but downtrend -> partial position, not full."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(5):
        store.save_news_event(_event(event_id=f"evt_b_{i}", sentiment_score=0.7))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot(price=90.0, sma_200=100.0))  # downtrend
    assert decision.action == "BUY"
    assert decision.target_pct == 0.5
    assert "trend down" in decision.reasoning


def test_all_bearish_returns_sell_flat(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    for i in range(5):
        store.save_news_event(_event(event_id=f"evt_bear_{i}", sentiment_score=-0.7))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot())
    assert decision.action == "SELL"
    assert decision.target_pct == 0.0
    assert "bearish" in decision.reasoning


def test_mixed_sentiment_within_neutral_band_returns_hold(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_news_event(_event(event_id="evt_a", sentiment_score=0.3))
    store.save_news_event(_event(event_id="evt_b", sentiment_score=-0.3))
    store.save_news_event(_event(event_id="evt_c", sentiment_score=0.05))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "within neutral band" in decision.reasoning


def test_recency_weighting_recent_outweighs_old(tmp_path):
    """A recent strongly-bullish event should beat older mildly-bearish events
    when recency half-life is short."""
    store = Store(tmp_path / "trader.sqlite")
    now = datetime.now(UTC)
    # Five mildly-bearish events from 24h ago
    for i in range(5):
        store.save_news_event(
            _event(
                event_id=f"evt_old_bear_{i}",
                sentiment_score=-0.4,
                published_at=now - timedelta(hours=24),
            )
        )
    # One very-fresh strongly-bullish event
    store.save_news_event(
        _event(
            event_id="evt_fresh_bull",
            sentiment_score=0.9,
            urgency="breaking",
            published_at=now - timedelta(minutes=10),
        )
    )
    # Tight half-life makes the 24h-old events decay by ~64x relative to fresh
    brain = SentimentMomentumBrain(store=store, recency_half_life_hours=4.0)
    decision = brain.decide(_snapshot())
    assert decision.action == "BUY"


def test_breaking_urgency_dominates_normal_urgency(tmp_path):
    """A single breaking-urgency bullish event should outweigh a few
    normal-urgency mildly-bearish ones (urgency weight = 1.0 vs 0.4).
    With 3 mildly-bear and 1 breaking-bull, the breaking event tips the
    aggregate above the +0.15 buy threshold."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(3):
        store.save_news_event(_event(event_id=f"evt_norm_bear_{i}", sentiment_score=-0.3, urgency="normal"))
    store.save_news_event(_event(event_id="evt_breaking_bull", sentiment_score=0.8, urgency="breaking"))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot())
    assert decision.action == "BUY"


def test_irrelevant_single_name_events_are_filtered(tmp_path):
    """An AAPL-only single-name event should not count for QQQ trading
    unless QQQ is in index_exposure."""
    store = Store(tmp_path / "trader.sqlite")
    # 5 events tagged as AAPL single_name with no QQQ exposure
    for i in range(5):
        store.save_news_event(
            _event(
                event_id=f"evt_aapl_only_{i}",
                sentiment_score=0.8,
                asset_scope=["single_name"],
                index_exposure=[],
                entity_tickers=["AAPL"],
            )
        )
    brain = SentimentMomentumBrain(store=store, min_events_for_signal=3)
    decision = brain.decide(_snapshot(ticker="QQQ"))
    # No relevant events -> HOLD
    assert decision.action == "HOLD"


def test_single_name_event_with_index_exposure_is_relevant(tmp_path):
    """AAPL event that names QQQ in index_exposure should count for QQQ trading."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(5):
        store.save_news_event(
            _event(
                event_id=f"evt_aapl_qqq_{i}",
                sentiment_score=0.8,
                asset_scope=["single_name"],
                index_exposure=["QQQ"],
                entity_tickers=["AAPL"],
            )
        )
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot(ticker="QQQ"))
    assert decision.action == "BUY"


def test_old_events_outside_lookback_window_excluded(tmp_path):
    store = Store(tmp_path / "trader.sqlite")
    now = datetime.now(UTC)
    # 5 strongly-bullish events from a week ago
    for i in range(5):
        store.save_news_event(
            _event(
                event_id=f"evt_ancient_{i}",
                sentiment_score=0.9,
                published_at=now - timedelta(days=7),
            )
        )
    brain = SentimentMomentumBrain(store=store, lookback_hours=48)
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"  # all events excluded by lookback


def test_deterministic_for_same_store(tmp_path):
    """Same events + same snapshot -> same Decision."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(4):
        store.save_news_event(_event(event_id=f"evt_d_{i}", sentiment_score=0.4))
    brain = SentimentMomentumBrain(store=store)
    snap = _snapshot()
    d1 = brain.decide(snap)
    d2 = brain.decide(snap)
    assert d1.action == d2.action
    assert d1.target_pct == d2.target_pct
    assert d1.confidence == d2.confidence


def test_decision_records_zero_llm_cost(tmp_path):
    """SentimentMomentumBrain is deterministic — must not record any LLM cost."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(4):
        store.save_news_event(_event(event_id=f"evt_z_{i}", sentiment_score=0.5))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot())
    assert decision.llm_cost_usd == 0.0
    assert decision.llm_model is None
    assert decision.llm_prompt_hash is None


def test_trend_unknown_when_sma200_missing(tmp_path):
    """If the snapshot has no SMA200, bullish sentiment still triggers BUY but
    at half exposure (we don't know the trend)."""
    store = Store(tmp_path / "trader.sqlite")
    for i in range(5):
        store.save_news_event(_event(event_id=f"evt_t_{i}", sentiment_score=0.6))
    brain = SentimentMomentumBrain(store=store)
    decision = brain.decide(_snapshot(sma_200=None))
    assert decision.action == "BUY"
    assert decision.target_pct == 0.5
    assert "trend unknown" in decision.reasoning


def test_runner_includes_sentiment_momentum_when_store_provided(tmp_path, monkeypatch):
    """Verify runner.all_brains() registers SentimentMomentumBrain when store is passed."""
    from trader.config import get_settings
    from trader.runner import all_brains

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    store = Store(tmp_path / "trader.sqlite")
    brains = all_brains(get_settings(), store=store)
    assert any(b.name == "SentimentMomentumBrain" for b in brains)
    get_settings.cache_clear()


def test_runner_omits_sentiment_momentum_when_no_store(monkeypatch):
    """all_brains without a store should not include SentimentMomentumBrain
    (the brain needs a store to query events)."""
    from trader.config import get_settings
    from trader.runner import all_brains

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()

    brains = all_brains(get_settings())
    assert not any(b.name == "SentimentMomentumBrain" for b in brains)
    get_settings.cache_clear()
