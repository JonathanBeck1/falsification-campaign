"""MacroEventBrain (Fed-only) behavior tests.

Per brain/decisions/2026-05-21-horse-race-phase-2.md. Covers: empty Fed feed,
sub-threshold sentiment, Conservative multi-event confirmation, Aggressive
single-event confirmation, bullish/bearish action assignment, recency decay
effect, filter rejects non-Fed events, and constructor validation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from trader.normalization.models import Event
from trader.signals.macro_event import (
    FED_EVENT_TYPE,
    FED_SOURCE,
    MacroEventBrain,
    macro_event_aggressive,
    macro_event_conservative,
)
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot
from trader.storage.store import Store

SNAPSHOT_TS = datetime(2026, 5, 18, 20, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def _snapshot() -> DailySnapshot:
    bar = Bar(
        timestamp=SNAPSHOT_TS,
        open=400.0,
        high=400.0,
        low=400.0,
        close=400.0,
        volume=1_000_000,
    )
    return DailySnapshot(
        snapshot_id=f"macro-test-{uuid.uuid4()}",
        trade_date=date(2026, 5, 18),
        ticker="QQQ",
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=400.0,
        sma_200=400.0,
        rsi_14=50.0,
        realized_vol_20d=0.1,
        news=[],
        macro=MacroSnapshot(),
    )


def _fed_event(
    *,
    days_ago: float,
    sentiment_score: float,
    urgency: str = "normal",
    credibility: float = 0.7,
    source: str = FED_SOURCE,
    event_type: str = FED_EVENT_TYPE,
) -> Event:
    published = SNAPSHOT_TS - timedelta(days=days_ago)
    return Event(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        source=source,
        title=f"Fed event (sent={sentiment_score:+.2f}, age={days_ago:.0f}d)",
        published_at=published,
        observed_at=published,
        ingested_at=published,
        event_type=event_type,
        sentiment_score=sentiment_score,
        urgency=urgency,
        novelty_score=0.5,
        source_credibility=credibility,
    )


# ── Empty / sub-threshold ────────────────────────────────────────────────


def test_empty_store_returns_hold_neutral(tmp_path):
    brain = macro_event_conservative(store=_store(tmp_path))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert decision.target_pct == 0.40  # Conservative neutral
    assert "no recent Fed activity" in decision.reasoning


def test_aggressive_empty_store_uses_aggressive_neutral(tmp_path):
    brain = macro_event_aggressive(store=_store(tmp_path))
    decision = brain.decide(_snapshot())
    assert decision.target_pct == 0.50  # Aggressive neutral


def test_sub_threshold_aggregate_returns_hold(tmp_path):
    store = _store(tmp_path)
    # Aggressive needs |sentiment| >= 0.10 aggregate. Plant 0.05.
    store.save_news_event(_fed_event(days_ago=1.0, sentiment_score=0.05))
    decision = macro_event_aggressive(store=store).decide(_snapshot())
    assert decision.action == "HOLD"
    assert "in [" in decision.reasoning  # sub-threshold reasoning marker


# ── Conservative confirming check ────────────────────────────────────────


def test_conservative_single_weak_event_does_not_confirm(tmp_path):
    store = _store(tmp_path)
    # Aggregate sentiment will cross +0.30 — but only one same-direction
    # event exists, and it's not breaking+credible. Should HOLD.
    store.save_news_event(_fed_event(days_ago=2.0, sentiment_score=0.6))
    decision = macro_event_conservative(store=store).decide(_snapshot())
    assert decision.action == "HOLD"
    assert "confirmation failed" in decision.reasoning


def test_conservative_two_same_direction_events_confirm(tmp_path):
    store = _store(tmp_path)
    store.save_news_event(_fed_event(days_ago=1.0, sentiment_score=0.5))
    store.save_news_event(_fed_event(days_ago=10.0, sentiment_score=0.4))
    decision = macro_event_conservative(store=store).decide(_snapshot())
    assert decision.action == "BUY"
    assert decision.target_pct == 0.60  # Conservative target_long


def test_conservative_breaking_credible_single_event_confirms(tmp_path):
    store = _store(tmp_path)
    store.save_news_event(
        _fed_event(days_ago=0.5, sentiment_score=0.7, urgency="breaking", credibility=0.85)
    )
    decision = macro_event_conservative(store=store).decide(_snapshot())
    assert decision.action == "BUY"
    assert decision.target_pct == 0.60


def test_conservative_breaking_but_low_credibility_does_not_confirm(tmp_path):
    store = _store(tmp_path)
    # urgency=breaking but credibility 0.5 (below 0.8 floor) — should still need 2 events.
    store.save_news_event(
        _fed_event(days_ago=0.5, sentiment_score=0.7, urgency="breaking", credibility=0.5)
    )
    decision = macro_event_conservative(store=store).decide(_snapshot())
    assert decision.action == "HOLD"


# ── Aggressive triggers on single event ──────────────────────────────────


def test_aggressive_single_event_triggers_bullish(tmp_path):
    store = _store(tmp_path)
    store.save_news_event(_fed_event(days_ago=2.0, sentiment_score=0.4))
    decision = macro_event_aggressive(store=store).decide(_snapshot())
    assert decision.action == "BUY"
    assert decision.target_pct == 1.00  # Aggressive target_long


def test_aggressive_single_bearish_event_triggers_sell(tmp_path):
    store = _store(tmp_path)
    store.save_news_event(_fed_event(days_ago=2.0, sentiment_score=-0.4))
    decision = macro_event_aggressive(store=store).decide(_snapshot())
    assert decision.action == "SELL"
    assert decision.target_pct == 0.0


# ── Recency decay ────────────────────────────────────────────────────────


def test_recency_decay_dampens_old_events(tmp_path):
    """Aggressive half-life is 3d. An event 10 half-lives old should
    contribute ~0.001x its raw sentiment to the aggregate."""
    store = _store(tmp_path)
    # Strong bullish event 30 days ago, weak bearish event 1 day ago.
    # Aggressive lookback is 14d — old event excluded entirely.
    store.save_news_event(_fed_event(days_ago=1.0, sentiment_score=-0.30))
    decision = macro_event_aggressive(store=store).decide(_snapshot())
    assert decision.action == "SELL"


def test_conservative_recency_decay_keeps_old_events_in_window(tmp_path):
    """Conservative lookback is 90d. A 60-day-old event is included but
    decayed (half-life 14d) by 2^(-60/14) ~= 0.05x."""
    store = _store(tmp_path)
    # 1 fresh dovish + 1 ancient hawkish should net bullish post-decay.
    store.save_news_event(_fed_event(days_ago=1.0, sentiment_score=0.6))
    store.save_news_event(_fed_event(days_ago=60.0, sentiment_score=-0.6))
    # Only one same-direction event after decay — won't confirm.
    decision = macro_event_conservative(store=store).decide(_snapshot())
    assert decision.action == "HOLD"


# ── Filter excludes non-Fed events ───────────────────────────────────────


def test_brain_ignores_non_fed_source(tmp_path):
    store = _store(tmp_path)
    # Save a finnhub event with strong sentiment — should be ignored.
    store.save_news_event(
        _fed_event(
            days_ago=1.0,
            sentiment_score=0.9,
            source="finnhub",
            event_type=FED_EVENT_TYPE,  # right event_type, wrong source
        )
    )
    decision = macro_event_aggressive(store=store).decide(_snapshot())
    assert decision.action == "HOLD"
    assert "no recent Fed activity" in decision.reasoning


def test_brain_ignores_non_fed_event_type(tmp_path):
    store = _store(tmp_path)
    # Right source, wrong event_type — should be ignored.
    store.save_news_event(
        _fed_event(
            days_ago=1.0,
            sentiment_score=0.9,
            event_type="earnings_surprise",
        )
    )
    decision = macro_event_aggressive(store=store).decide(_snapshot())
    assert decision.action == "HOLD"


# ── Determinism ──────────────────────────────────────────────────────────


def test_deterministic_same_store_same_decision(tmp_path):
    store = _store(tmp_path)
    store.save_news_event(_fed_event(days_ago=1.0, sentiment_score=0.3))
    store.save_news_event(_fed_event(days_ago=5.0, sentiment_score=0.25))
    snap = _snapshot()
    d1 = macro_event_conservative(store=store).decide(snap)
    d2 = macro_event_conservative(store=store).decide(snap)
    assert d1.action == d2.action
    assert d1.target_pct == d2.target_pct


# ── Constructor validation ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"lookback_days": 0}, "lookback_days must be positive"),
        ({"lookback_days": -1}, "lookback_days must be positive"),
        ({"recency_half_life_days": 0}, "recency_half_life_days must be positive"),
        ({"min_events_for_signal": 0}, "min_events_for_signal must be >= 1"),
        ({"buy_threshold": 0.0}, "buy_threshold must be > 0"),
        ({"buy_threshold": -0.1}, "buy_threshold must be > 0"),
        ({"sell_threshold": 0.0}, "sell_threshold must be < 0"),
        ({"sell_threshold": 0.1}, "sell_threshold must be < 0"),
        ({"target_long": 1.5}, "target_long must be in"),
        ({"target_long": -0.1}, "target_long must be in"),
        ({"target_short": 1.5}, "target_short must be in"),
        ({"neutral_target": 2.0}, "neutral_target must be in"),
    ],
)
def test_constructor_rejects_bad_params(tmp_path, kwargs: dict, match: str):
    defaults = dict(
        store=_store(tmp_path),
        lookback_days=30,
        recency_half_life_days=7.0,
        min_events_for_signal=1,
        buy_threshold=0.2,
        sell_threshold=-0.2,
        target_long=0.7,
        target_short=0.0,
        neutral_target=0.5,
        require_multi_event_confirmation=False,
        name="x",
    )
    defaults.update(kwargs)
    with pytest.raises(ValueError, match=match):
        MacroEventBrain(**defaults)


def test_factories_set_expected_dial_values(tmp_path):
    cons = macro_event_conservative(store=_store(tmp_path))
    assert cons._lookback_days == 90
    assert cons._buy_threshold == 0.30
    assert cons._target_long == 0.60
    assert cons._require_multi_event_confirmation is True

    agg = macro_event_aggressive(store=_store(tmp_path))
    assert agg._lookback_days == 14
    assert agg._buy_threshold == 0.10
    assert agg._target_long == 1.00
    assert agg._require_multi_event_confirmation is False


def test_uses_llm_is_false():
    """MacroEventBrain is deterministic — Phase 2 has no LLM brain in this strategy."""
    assert MacroEventBrain.uses_llm is False
