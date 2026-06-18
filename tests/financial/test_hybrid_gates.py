"""Preventive cost gate + tier-1 deterministic short-circuit tests.

Per `brain/20_llm_decision_boundary_adr.md` drift 2: the LLM must be skipped
BEFORE the call when the daily budget is exhausted OR the classical signal
is confident with no breaking news in the recent window. These tests pin
both gates and the runner-level pre-roster check.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot, NewsItem
from trader.storage.store import Store


def _make_snapshot(now: datetime | None = None) -> DailySnapshot:
    """Bullish baseline: ClassicalBrain returns BUY@100% with confidence 0.6."""
    now = now or datetime(2026, 5, 19, 13, tzinfo=UTC)
    bars = [
        Bar(
            timestamp=now - timedelta(hours=2 - h),
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
        trade_date=now.date(),
        ticker="SPY",
        latest_bar=bars[-1],
        recent_bars=bars,
        sma_50=100.0,
        sma_200=98.0,
        rsi_14=55.0,
        realized_vol_20d=0.15,
        news=[
            NewsItem(
                headline="Routine market chatter",
                summary="",
                source="x.com",
                published_at=now,
            ),
        ],
        macro=MacroSnapshot(vix=14.0, yield_curve_10y_2y=0.5, fed_funds=5.0, cpi_yoy=3.0),
    )


def _llm_should_not_be_called(**_kwargs):
    raise AssertionError("LLM was called even though a gate should have skipped it")


def _llm_returns_valid_features(**_kwargs):
    from trader.llm.client import LLMResponse

    return LLMResponse(
        content="{}",
        parsed={
            "sentiment_label": "bullish",
            "event_tags": ["earnings"],
            "severity_bucket": "low",
            "abstain_reason": None,
        },
        model="claude-haiku-4-5-20251001",
        input_tokens=200,
        output_tokens=40,
        cached_tokens=0,
        cache_creation_tokens=0,
        cost_usd=0.001,
        latency_ms=400,
        prompt_hash="hash01",
    )


# ── Preventive cost gate ────────────────────────────────────────────────────


def test_budget_exhausted_falls_back_without_llm_call(tmp_path):
    """When the daily LLM spend equals the cap, HybridBrain must NOT call the
    LLM. The classical base decision passes through with `llm_skipped` in the
    notes."""
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    store.record_llm_call(
        decision_id=None,
        brain="prior_run",
        model="claude-haiku-4-5-20251001",
        prompt_hash="prior",
        input_tokens=10000,
        output_tokens=10000,
        cached_tokens=0,
        cost_usd=1.0,  # already at the $1 cap
        latency_ms=100,
    )

    fake_llm = SimpleNamespace(complete=_llm_should_not_be_called)
    brain = HybridBrain(llm=fake_llm, store=store, daily_budget_usd=1.0)
    decision = brain.decide(_make_snapshot())

    assert decision.action == "BUY"  # classical base
    assert decision.target_pct == 1.0
    assert "llm_skipped=llm_budget_exhausted" in decision.reasoning
    assert decision.llm_cost_usd == 0.0
    assert decision.llm_model is None


def test_budget_below_cap_does_call_llm(tmp_path):
    """If today's spend is under the cap, the LLM should be called normally."""
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    store.record_llm_call(
        decision_id=None,
        brain="prior",
        model="m",
        prompt_hash="p",
        input_tokens=100,
        output_tokens=100,
        cached_tokens=0,
        cost_usd=0.1,
        latency_ms=10,
    )

    fake_llm = SimpleNamespace(complete=_llm_returns_valid_features)
    # confidence threshold above classical's 0.6 → short-circuit can't fire
    brain = HybridBrain(
        llm=fake_llm,
        store=store,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.99,
    )
    decision = brain.decide(_make_snapshot())

    assert decision.llm_model == "claude-haiku-4-5-20251001"
    assert "llm_skipped" not in decision.reasoning


# ── Tier-1 deterministic short-circuit ─────────────────────────────────────


def test_short_circuit_skips_llm_when_classical_confident_and_no_breaking(tmp_path):
    """Classical confidence > threshold AND no breaking events in lookback →
    skip the LLM and pass base through."""
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    fake_llm = SimpleNamespace(complete=_llm_should_not_be_called)
    brain = HybridBrain(
        llm=fake_llm,
        store=store,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.5,  # below classical's 0.6 → fires
    )
    decision = brain.decide(_make_snapshot())

    assert decision.action == "BUY"
    assert decision.target_pct == 1.0
    assert "llm_skipped=classical_decisive_no_breaking_news" in decision.reasoning


def test_short_circuit_without_store_does_not_skip_llm():
    """Without a store, HybridBrain cannot prove there is no breaking news, so
    it should run the LLM instead of quietly short-circuiting."""
    from trader.signals.hybrid import HybridBrain

    fake_llm = SimpleNamespace(complete=_llm_returns_valid_features)
    brain = HybridBrain(
        llm=fake_llm,
        store=None,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.5,
    )
    decision = brain.decide(_make_snapshot())

    assert decision.llm_model == "claude-haiku-4-5-20251001"
    assert "llm_skipped" not in decision.reasoning


def test_short_circuit_does_not_fire_when_classical_unconfident(tmp_path):
    """When classical confidence is below threshold, the LLM runs even if no
    breaking events have been observed."""
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    fake_llm = SimpleNamespace(complete=_llm_returns_valid_features)
    brain = HybridBrain(
        llm=fake_llm,
        store=store,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.99,  # above 0.6 → no short-circuit
    )
    decision = brain.decide(_make_snapshot())

    assert decision.llm_model == "claude-haiku-4-5-20251001"
    assert "llm_skipped" not in decision.reasoning


def test_short_circuit_does_not_fire_with_recent_breaking_event(tmp_path):
    """Even if classical is confident, a breaking-urgency event in the
    lookback window must force the LLM to run."""
    from trader.normalization.models import Event
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    snapshot = _make_snapshot()
    now = snapshot.latest_bar.timestamp
    store.save_news_event(
        Event(
            event_id="evt_breaking_test",
            source="x_test",
            source_url="",
            title="Flash crash, all bets off",
            summary="",
            published_at=now - timedelta(hours=1),
            observed_at=now - timedelta(hours=1),
            ingested_at=now,
            classified_at=now,
            entities=[],
            asset_scope=["macro"],
            index_exposure=["SPY"],
            event_type="macro_surprise",
            sentiment="negative",
            sentiment_score=-0.7,
            urgency="breaking",
            novelty_score=0.9,
            source_credibility=0.9,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
    )

    fake_llm = SimpleNamespace(complete=_llm_returns_valid_features)
    brain = HybridBrain(
        llm=fake_llm,
        store=store,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.5,
        breaking_lookback_hours=24,
    )
    decision = brain.decide(snapshot)

    # LLM must have been called — the breaking event blocks the short-circuit
    assert decision.llm_model == "claude-haiku-4-5-20251001"
    assert "llm_skipped" not in decision.reasoning


def test_short_circuit_respects_lookback_window(tmp_path):
    """A breaking event OUTSIDE the lookback window does NOT block the
    short-circuit."""
    from trader.normalization.models import Event
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    snapshot = _make_snapshot()
    now = snapshot.latest_bar.timestamp
    store.save_news_event(
        Event(
            event_id="evt_old_breaking",
            source="x",
            source_url="",
            title="Old crisis from last week",
            summary="",
            published_at=now - timedelta(days=7),
            observed_at=now - timedelta(days=7),
            ingested_at=now,
            classified_at=now,
            entities=[],
            asset_scope=["macro"],
            index_exposure=[],
            event_type="macro_surprise",
            sentiment="negative",
            sentiment_score=-0.5,
            urgency="breaking",
            novelty_score=0.5,
            source_credibility=0.9,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
    )

    fake_llm = SimpleNamespace(complete=_llm_should_not_be_called)
    brain = HybridBrain(
        llm=fake_llm,
        store=store,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.5,
        breaking_lookback_hours=24,  # 24h window — 7d-old event doesn't count
    )
    decision = brain.decide(snapshot)
    assert "llm_skipped=classical_decisive_no_breaking_news" in decision.reasoning


def test_short_circuit_uses_snapshot_time_for_breaking_lookback(tmp_path):
    """Historical replay must query breaking news relative to the snapshot
    timestamp, not the current wall clock."""
    from trader.normalization.models import Event
    from trader.signals.hybrid import HybridBrain

    store = Store(tmp_path / "trader.sqlite")
    snap_time = datetime(2024, 1, 15, 13, tzinfo=UTC)
    store.save_news_event(
        Event(
            event_id="evt_replay_breaking",
            source="x",
            source_url="",
            title="Replay-time breaking event",
            summary="",
            published_at=snap_time - timedelta(hours=1),
            observed_at=snap_time - timedelta(hours=1),
            ingested_at=snap_time - timedelta(hours=1),
            classified_at=snap_time - timedelta(hours=1),
            entities=[],
            asset_scope=["macro"],
            index_exposure=[],
            event_type="macro_surprise",
            sentiment="negative",
            sentiment_score=-0.5,
            urgency="breaking",
            novelty_score=0.8,
            source_credibility=0.9,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
    )

    fake_llm = SimpleNamespace(complete=_llm_returns_valid_features)
    brain = HybridBrain(
        llm=fake_llm,
        store=store,
        daily_budget_usd=1.0,
        classical_confidence_threshold=0.5,
        breaking_lookback_hours=24,
    )
    decision = brain.decide(_make_snapshot(now=snap_time))

    assert decision.llm_model == "claude-haiku-4-5-20251001"
    assert "llm_skipped" not in decision.reasoning


# ── Runner-level pre-roster gate ───────────────────────────────────────────


def test_all_brains_skips_hybrid_when_budget_exhausted(tmp_path, monkeypatch):
    """The runner's all_brains() must NOT instantiate HybridBrain if the
    daily budget has already been spent. Prevents wasted construction +
    closes the race where two parallel runs both pass an internal-only gate."""
    from trader.config import get_settings
    from trader.runner import all_brains
    from trader.signals.hybrid import HybridBrain

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("TRADER_LLM_DAILY_BUDGET_USD", "0.50")
    get_settings.cache_clear()

    store = Store(tmp_path / "trader.sqlite")
    store.record_llm_call(
        decision_id=None,
        brain="prior",
        model="m",
        prompt_hash="p",
        input_tokens=100,
        output_tokens=100,
        cached_tokens=0,
        cost_usd=0.50,  # at cap
        latency_ms=10,
    )

    brains = all_brains(get_settings(), store=store)
    assert not any(isinstance(b, HybridBrain) for b in brains)
    get_settings.cache_clear()


def test_all_brains_includes_hybrid_when_budget_available(tmp_path, monkeypatch):
    """When an LLM key is configured and budget is available, HybridBrain
    should be in the roster."""
    from trader.config import get_settings
    from trader.runner import all_brains
    from trader.signals.hybrid import HybridBrain

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("TRADER_LLM_DAILY_BUDGET_USD", "1.0")
    get_settings.cache_clear()

    store = Store(tmp_path / "trader.sqlite")
    brains = all_brains(get_settings(), store=store)
    assert any(isinstance(b, HybridBrain) for b in brains)
    get_settings.cache_clear()


# ── Store helper ───────────────────────────────────────────────────────────


def test_count_breaking_events_since_filters_by_observed_at(tmp_path):
    """Ensures the store query filters on observed_at, not published_at — so a
    back-dated `published_at` cannot bypass the gate."""
    from trader.normalization.models import Event

    store = Store(tmp_path / "trader.sqlite")
    now = datetime.now(UTC)

    # Backdated publish, recent observe — should still count as "recent"
    store.save_news_event(
        Event(
            event_id="evt_backdated",
            source="x",
            source_url="",
            title="t",
            summary="",
            published_at=now - timedelta(days=30),
            observed_at=now - timedelta(minutes=5),  # JUST observed
            ingested_at=now,
            classified_at=now,
            entities=[],
            asset_scope=[],
            index_exposure=[],
            event_type="macro_surprise",
            sentiment="negative",
            sentiment_score=-0.5,
            urgency="breaking",
            novelty_score=0.5,
            source_credibility=0.9,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
    )
    # Recent publish, old observe — should NOT count
    store.save_news_event(
        Event(
            event_id="evt_old_observe",
            source="y",
            source_url="",
            title="t",
            summary="",
            published_at=now,
            observed_at=now - timedelta(days=2),
            ingested_at=now,
            classified_at=now,
            entities=[],
            asset_scope=[],
            index_exposure=[],
            event_type="macro_surprise",
            sentiment="negative",
            sentiment_score=-0.5,
            urgency="breaking",
            novelty_score=0.5,
            source_credibility=0.9,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
    )

    one_day_ago = now - timedelta(hours=24)
    assert store.count_breaking_events_since(one_day_ago) == 1


def test_count_breaking_events_since_ignores_non_breaking_urgency(tmp_path):
    """Only urgency='breaking' rows count."""
    from trader.normalization.models import Event

    store = Store(tmp_path / "trader.sqlite")
    now = datetime.now(UTC)
    store.save_news_event(
        Event(
            event_id="evt_high",
            source="x",
            source_url="",
            title="t",
            summary="",
            published_at=now,
            observed_at=now,
            ingested_at=now,
            classified_at=now,
            entities=[],
            asset_scope=[],
            index_exposure=[],
            event_type="macro_surprise",
            sentiment="negative",
            sentiment_score=-0.5,
            urgency="high",  # not breaking
            novelty_score=0.5,
            source_credibility=0.9,
            evidence=[],
            model_outputs=[],
            raw_artifact_path="",
        )
    )
    assert store.count_breaking_events_since(now - timedelta(hours=24)) == 0


def test_count_breaking_events_since_empty_store(tmp_path):
    """No rows at all → count is 0, not an error."""
    store = Store(tmp_path / "trader.sqlite")
    assert store.count_breaking_events_since(datetime.now(UTC)) == 0


# Silences the "unused import Path" diagnostic that some envs emit.
_ = Path
