"""EarningsToneBrain behavior tests.

Uses a `FakeLLMClient` that returns canned `EarningsToneFeatures` JSON so
tests are deterministic and do NOT hit any LLM API. Covers: empty store
(no LLM call), sub-min events (no LLM call), abstain, Conservative
high-confidence + majority-breadth gates, Aggressive single-event triggers,
bullish/bearish + conflict resolution, filter rejects non-8-K, constructor
validation, uses_llm=True.

Per brain/decisions/2026-05-21-horse-race-phase-3.md.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from trader.llm.client import LLMResponse
from trader.normalization.models import Entity, Event
from trader.signals.earnings_tone import (
    EARNINGS_EVENT_TYPES,
    POLICY_AGGRESSIVE,
    POLICY_CONSERVATIVE,
    SEC_SOURCE,
    EarningsToneBrain,
    EarningsTonePolicy,
)
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot
from trader.storage.store import Store

SNAPSHOT_TS = datetime(2026, 5, 18, 20, 0, tzinfo=UTC)


class _FakeLLMClient:
    """Returns a pre-canned LLMResponse. Records the last user/system prompt."""

    def __init__(self, features_payload: dict | None = None, *, raise_on_call: bool = False) -> None:
        self.features_payload = features_payload
        self.raise_on_call = raise_on_call
        self.calls: list[tuple[str, str]] = []
        self.model = "fake-model"

    def complete(self, *, system: str, user: str, response_format_json: bool = True, max_tokens: int = 256, **_kwargs) -> LLMResponse:
        if self.raise_on_call:
            raise AssertionError("LLM should not have been called")
        self.calls.append((system, user))
        content = json.dumps(self.features_payload) if self.features_payload is not None else "not_json"
        return LLMResponse(
            content=content,
            parsed=None,
            model=self.model,
            input_tokens=10,
            output_tokens=20,
            cached_tokens=0,
            cache_creation_tokens=0,
            cost_usd=0.05,
            latency_ms=42,
            prompt_hash="fake-prompt-hash",
        )


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
        snapshot_id=f"earnings-test-{uuid.uuid4()}",
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


def _sec_event(
    *,
    days_ago: float,
    ticker: str = "AAPL",
    event_type: str = "earnings_surprise",
    source: str = SEC_SOURCE,
) -> Event:
    published = SNAPSHOT_TS - timedelta(days=days_ago)
    return Event(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        source=source,
        title=f"{ticker} {event_type} 8-K",
        published_at=published,
        observed_at=published,
        ingested_at=published,
        event_type=event_type,
        sentiment_score=0.0,
        urgency="normal",
        novelty_score=0.5,
        source_credibility=0.8,
        entities=[Entity(name=ticker, ticker=ticker, confidence=0.9, role="primary")],
    )


def _features(**overrides) -> dict:
    base = {
        "schema_version": "earnings-tone-v1",
        "aggregate_tone": "neutral",
        "guidance_signal": "none_visible",
        "breadth": "single_name_only",
        "confidence": "low",
        "abstain_reason": None,
    }
    base.update(overrides)
    return base


def _brain(
    tmp_path: Path,
    *,
    policy: EarningsTonePolicy = POLICY_AGGRESSIVE,
    lookback_days: int = 14,
    min_events_for_signal: int = 1,
    fake_llm: _FakeLLMClient | None = None,
    name: str = "EarningsToneTest",
) -> tuple[EarningsToneBrain, _FakeLLMClient, Store]:
    store = _store(tmp_path)
    llm = fake_llm or _FakeLLMClient(features_payload=_features())
    brain = EarningsToneBrain(
        llm=llm,
        store=store,
        policy=policy,
        lookback_days=lookback_days,
        min_events_for_signal=min_events_for_signal,
        name=name,
    )
    return brain, llm, store


# ── No-LLM-call paths ───────────────────────────────────────────────────


def test_empty_store_returns_hold_no_llm_call(tmp_path):
    llm = _FakeLLMClient(raise_on_call=True)
    brain, _, _ = _brain(tmp_path, fake_llm=llm)
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert decision.target_pct == POLICY_AGGRESSIVE.neutral_target
    assert llm.calls == []


def test_sub_min_events_returns_hold_no_llm_call(tmp_path):
    llm = _FakeLLMClient(raise_on_call=True)
    brain, _, store = _brain(
        tmp_path,
        policy=POLICY_CONSERVATIVE,
        lookback_days=30,
        min_events_for_signal=3,
        fake_llm=llm,
    )
    store.save_news_event(_sec_event(days_ago=1.0, ticker="AAPL"))
    store.save_news_event(_sec_event(days_ago=2.0, ticker="MSFT"))
    # Only 2 events, need 3.
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "need 3" in decision.reasoning
    assert llm.calls == []


# ── Filter excludes non-8-K events ───────────────────────────────────────


def test_brain_ignores_non_sec_source(tmp_path):
    llm = _FakeLLMClient(raise_on_call=True)
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    # Right event_type but wrong source.
    store.save_news_event(
        _sec_event(days_ago=1.0, source="finnhub", event_type="earnings_surprise")
    )
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "no recent earnings 8-Ks" in decision.reasoning
    assert llm.calls == []


def test_brain_ignores_non_earnings_event_type(tmp_path):
    llm = _FakeLLMClient(raise_on_call=True)
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    # Right source but wrong event_type.
    store.save_news_event(
        _sec_event(days_ago=1.0, event_type="fed_commentary")
    )
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert llm.calls == []


# ── Aggressive bullish path ──────────────────────────────────────────────


def test_aggressive_bullish_high_conf_buys(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="raised",
            breadth="all_aligned",
            confidence="high",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "BUY"
    assert decision.target_pct == POLICY_AGGRESSIVE.bullish_target  # 1.00
    assert len(llm.calls) == 1


def test_aggressive_bullish_low_conf_still_buys(tmp_path):
    """Aggressive does NOT require high confidence — low-conf bullish still triggers."""
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="unchanged",
            breadth="single_name_only",
            confidence="low",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "BUY"


# ── Conservative confidence/breadth gates ────────────────────────────────


def test_conservative_low_confidence_holds(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="raised",
            breadth="all_aligned",
            confidence="medium",
        )
    )
    brain, _, store = _brain(
        tmp_path,
        policy=POLICY_CONSERVATIVE,
        lookback_days=30,
        min_events_for_signal=1,
        fake_llm=llm,
    )
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert decision.target_pct == POLICY_CONSERVATIVE.neutral_target
    assert "conf=medium" in decision.reasoning


def test_conservative_single_name_breadth_holds(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="raised",
            breadth="single_name_only",
            confidence="high",
        )
    )
    brain, _, store = _brain(
        tmp_path,
        policy=POLICY_CONSERVATIVE,
        lookback_days=30,
        min_events_for_signal=1,
        fake_llm=llm,
    )
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "breadth=single_name_only" in decision.reasoning


def test_conservative_high_conf_majority_buys(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="raised",
            breadth="majority_aligned",
            confidence="high",
        )
    )
    brain, _, store = _brain(
        tmp_path,
        policy=POLICY_CONSERVATIVE,
        lookback_days=30,
        min_events_for_signal=1,
        fake_llm=llm,
    )
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "BUY"
    assert decision.target_pct == POLICY_CONSERVATIVE.bullish_target  # 0.60


# ── Conflict resolution ──────────────────────────────────────────────────


def test_bullish_tone_with_lowered_guidance_holds(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="lowered",
            breadth="all_aligned",
            confidence="high",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "conflict" in decision.reasoning


def test_bearish_tone_with_raised_guidance_holds(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bearish",
            guidance_signal="raised",
            breadth="all_aligned",
            confidence="high",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "conflict" in decision.reasoning


def test_bearish_tone_with_lowered_guidance_sells(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bearish",
            guidance_signal="lowered",
            breadth="all_aligned",
            confidence="high",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "SELL"
    assert decision.target_pct == POLICY_AGGRESSIVE.bearish_target  # 0.00


# ── Abstain ──────────────────────────────────────────────────────────────


def test_llm_abstain_holds(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",  # ignored when abstain is set
            confidence="high",
            abstain_reason="bundle too sparse",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "abstain" in decision.reasoning


# ── LLM error fallbacks ──────────────────────────────────────────────────


def test_invalid_json_response_holds_no_crash(tmp_path):
    llm = _FakeLLMClient(features_payload=None)  # returns "not_json"
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "json_decode" in decision.reasoning


def test_schema_violation_response_holds_no_crash(tmp_path):
    # Valid JSON but missing required field.
    llm = _FakeLLMClient(features_payload={"schema_version": "earnings-tone-v1"})
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.action == "HOLD"
    assert "schema_validation" in decision.reasoning


# ── LLM cost metadata propagation ────────────────────────────────────────


def test_decision_carries_llm_cost_metadata(tmp_path):
    llm = _FakeLLMClient(
        features_payload=_features(
            aggregate_tone="bullish",
            guidance_signal="raised",
            breadth="all_aligned",
            confidence="high",
        )
    )
    brain, _, store = _brain(tmp_path, fake_llm=llm)
    store.save_news_event(_sec_event(days_ago=1.0))
    decision = brain.decide(_snapshot())
    assert decision.llm_cost_usd == 0.05
    assert decision.llm_model == "fake-model"
    assert decision.llm_prompt_hash == "fake-prompt-hash"
    assert decision.llm_input_tokens == 10
    assert decision.llm_output_tokens == 20
    assert decision.llm_latency_ms == 42


# ── Constructor validation ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"lookback_days": 0}, "lookback_days must be positive"),
        ({"lookback_days": -1}, "lookback_days must be positive"),
        ({"min_events_for_signal": 0}, "min_events_for_signal must be >= 1"),
    ],
)
def test_constructor_rejects_bad_params(tmp_path, kwargs: dict, match: str):
    defaults = dict(
        llm=_FakeLLMClient(),
        store=_store(tmp_path),
        policy=POLICY_AGGRESSIVE,
        lookback_days=14,
        min_events_for_signal=1,
        name="x",
    )
    defaults.update(kwargs)
    with pytest.raises(ValueError, match=match):
        EarningsToneBrain(**defaults)


def test_uses_llm_is_true():
    assert EarningsToneBrain.uses_llm is True


def test_event_types_set_matches_spec():
    assert frozenset({"earnings_surprise", "guidance_raise", "guidance_lower"}) == EARNINGS_EVENT_TYPES


# ── Policy constants ─────────────────────────────────────────────────────


def test_policy_constants_match_spec_dial_values():
    assert POLICY_CONSERVATIVE.neutral_target == 0.40
    assert POLICY_CONSERVATIVE.bullish_target == 0.60
    assert POLICY_CONSERVATIVE.bearish_target == 0.00
    assert POLICY_CONSERVATIVE.require_high_confidence is True
    assert POLICY_CONSERVATIVE.require_majority_breadth is True

    assert POLICY_AGGRESSIVE.neutral_target == 0.50
    assert POLICY_AGGRESSIVE.bullish_target == 1.00
    assert POLICY_AGGRESSIVE.bearish_target == 0.00
    assert POLICY_AGGRESSIVE.require_high_confidence is False
    assert POLICY_AGGRESSIVE.require_majority_breadth is False
