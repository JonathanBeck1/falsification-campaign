"""Smoke tests for HybridBrain after the LLMFeatures/SizingPolicy refactor.

The brain now consumes strict enum features (no free floats) and routes
sizing through a versioned `SizingPolicy`. These tests verify the LLM →
policy → Decision pipe, plus the safe-default behavior when the LLM
returns junk.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot, NewsItem


def _make_snapshot() -> DailySnapshot:
    """Minimal DailySnapshot HybridBrain can decide on. Bullish baseline:
    price > SMA200, RSI mid-range, VIX low — ClassicalBrain returns BUY@100%."""
    now = datetime(2026, 5, 19, 13, tzinfo=UTC)
    bars = [
        Bar(
            timestamp=now.replace(hour=h),
            open=100.0 + h * 0.1,
            high=101.0 + h * 0.1,
            low=99.5 + h * 0.1,
            close=100.5 + h * 0.1,
            volume=1_000_000,
        )
        for h in range(3)
    ]
    return DailySnapshot(
        snapshot_id="snap_test",
        trade_date=date(2026, 5, 19),
        ticker="SPY",
        latest_bar=bars[-1],
        recent_bars=bars,
        sma_50=100.0,
        sma_200=98.0,
        rsi_14=55.0,
        realized_vol_20d=0.15,
        news=[
            NewsItem(
                headline="Fed minutes show split on rate path",
                summary="FOMC participants debated cuts.",
                source="marketwatch.com",
                published_at=now,
            ),
        ],
        macro=MacroSnapshot(vix=14.0, yield_curve_10y_2y=0.5, fed_funds=5.0, cpi_yoy=3.0),
    )


def _fake_llm(parsed):
    from trader.llm.client import LLMResponse

    resp = LLMResponse(
        content="" if parsed is None else "{}",
        parsed=parsed,
        model="claude-haiku-4-5-20251001",
        input_tokens=200,
        output_tokens=40,
        cached_tokens=0,
        cache_creation_tokens=0,
        cost_usd=0.001,
        latency_ms=850,
        prompt_hash="abc123def456",
    )
    return SimpleNamespace(complete=lambda **_kwargs: resp)


def test_hybrid_brain_bearish_high_severity_fomc_trims_position():
    """Compound risk-off signal should chain through the policy:
    classical BUY@100% → bearish halves (50%) → high cap stays (50%) → fomc halves (25%)."""
    from trader.signals.hybrid import HybridBrain

    fake_response_parsed = {
        "schema_version": "hybrid-features-v1",
        "sentiment_label": "bearish",
        "event_tags": ["fomc"],
        "severity_bucket": "high",
        "abstain_reason": None,
    }
    brain = HybridBrain(llm=_fake_llm(fake_response_parsed))
    decision = brain.decide(_make_snapshot())

    assert decision.action == "SELL"  # target dropped below base
    assert decision.target_pct == 0.25
    assert "policy=hybrid-policy-v2" in decision.reasoning
    assert "sentiment=bearish" in decision.reasoning
    assert "event=fomc" in decision.reasoning
    assert decision.llm_model == "claude-haiku-4-5-20251001"
    assert decision.llm_cost_usd == 0.001


def test_hybrid_brain_bullish_low_severity_passes_base_through():
    """Bullish + low severity + no special tags → classical BUY@100% survives."""
    from trader.signals.hybrid import HybridBrain

    brain = HybridBrain(
        llm=_fake_llm(
            {
                "sentiment_label": "bullish",
                "event_tags": ["earnings"],
                "severity_bucket": "low",
                "abstain_reason": None,
            }
        )
    )
    decision = brain.decide(_make_snapshot())
    assert decision.action == "BUY"
    assert decision.target_pct == 1.0


def test_hybrid_brain_survives_unparseable_llm_response():
    """Junk JSON falls back to safe_default — neutral/low/none/abstain — so the
    classical base decision passes through unchanged."""
    from trader.llm.client import LLMResponse
    from trader.signals.hybrid import HybridBrain

    junk = LLMResponse(
        content="not json at all",
        parsed=None,
        model="claude-haiku-4-5-20251001",
        input_tokens=200,
        output_tokens=10,
        cached_tokens=0,
        cache_creation_tokens=0,
        cost_usd=0.0005,
        latency_ms=400,
        prompt_hash="junk0001",
    )
    brain = HybridBrain(llm=SimpleNamespace(complete=lambda **_k: junk))
    decision = brain.decide(_make_snapshot())

    # safe_default abstains, so policy passes base through
    assert decision.action == "BUY"
    assert decision.target_pct == 1.0
    assert "llm_abstain=llm_response_unparseable" in decision.reasoning


def test_hybrid_brain_rejects_free_float_in_llm_payload():
    """Schema must reject the OLD free-float fields. If a stale prompt slips
    through and the model returns `regime_sentiment: -0.73`, validation fails
    and the safe default kicks in — instead of silently halving the position."""
    from trader.signals.hybrid import HybridBrain

    stale = {
        "regime_sentiment": -0.73,
        "event_severity": 0.85,
        "is_fed_day": True,
        "key_drivers": ["fed", "rates"],
    }
    brain = HybridBrain(llm=_fake_llm(stale))
    decision = brain.decide(_make_snapshot())
    # Old code would have silently halved target. New code falls back to base.
    assert decision.target_pct == 1.0
    assert "llm_abstain=llm_response_unparseable" in decision.reasoning


def test_hybrid_brain_llm_abstain_falls_back_to_base():
    """Explicit abstain → base decision wins, policy logs the reason."""
    from trader.signals.hybrid import HybridBrain

    brain = HybridBrain(
        llm=_fake_llm(
            {
                "sentiment_label": "neutral",
                "event_tags": ["none"],
                "severity_bucket": "low",
                "abstain_reason": "headlines_contradictory",
            }
        )
    )
    decision = brain.decide(_make_snapshot())
    assert decision.target_pct == 1.0
    assert "llm_abstain=headlines_contradictory" in decision.reasoning
