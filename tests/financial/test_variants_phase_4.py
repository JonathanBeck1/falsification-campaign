"""Phase 4 variant wiring: phase_4_variants, all_phase_variants, build_brain.

Per brain/decisions/2026-05-21-horse-race-phase-4.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trader.signals.classical import ClassicalBrain
from trader.signals.sentiment_momentum import SentimentMomentumBrain
from trader.signals.variants import (
    BrainVariantConfig,
    all_phase_variants,
    build_brain,
    phase_1_variants,
    phase_2_variants,
    phase_3_variants,
    phase_4_variants,
    variant_requires_store,
)
from trader.storage.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def test_phase_4_variants_returns_four_unique_names():
    configs = phase_4_variants()
    assert len(configs) == 4
    names = {c.name for c in configs}
    assert names == {
        "ClassicalConservative",
        "ClassicalAggressive",
        "SentimentMomentumConservative",
        "SentimentMomentumAggressive",
    }


def test_phase_4_variants_cover_both_strategies():
    configs = phase_4_variants()
    strategies = {c.strategy for c in configs}
    assert strategies == {"classical", "sentiment_momentum"}
    for c in configs:
        assert c.llm_model is None  # both deterministic
    profiles = {c.risk_profile for c in configs}
    assert profiles == {"conservative", "aggressive"}


def test_all_phase_variants_combines_four_phases():
    p1 = phase_1_variants()
    p2 = phase_2_variants()
    p3 = phase_3_variants()
    p4 = phase_4_variants()
    combined = all_phase_variants()
    assert len(combined) == len(p1) + len(p2) + len(p3) + len(p4)
    # Ordering: Phase 1, then 2, then 3, then 4.
    names = [v.name for v in combined]
    assert names[: len(p1)] == [v.name for v in p1]
    assert names[len(p1) : len(p1) + len(p2)] == [v.name for v in p2]
    assert names[len(p1) + len(p2) : len(p1) + len(p2) + len(p3)] == [v.name for v in p3]
    assert names[len(p1) + len(p2) + len(p3) :] == [v.name for v in p4]


def test_all_phase_variants_names_unique():
    names = [v.name for v in all_phase_variants()]
    assert len(set(names)) == len(names)


# ── build_brain branches ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config_name,expected_long_target,expected_sma_buffer",
    [
        ("ClassicalConservative", 0.70, 0.01),
        ("ClassicalAggressive", 1.0, 0.0),
    ],
)
def test_build_brain_classical_variants(
    tmp_path, config_name: str, expected_long_target: float, expected_sma_buffer: float
):
    cfg = next(v for v in phase_4_variants() if v.name == config_name)
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert isinstance(brain, ClassicalBrain)
    assert brain.name == config_name
    assert brain.uses_llm is False
    assert brain._long_target == expected_long_target
    assert brain._sma_buffer_pct == expected_sma_buffer


@pytest.mark.parametrize(
    "config_name,expected_floor,expected_lookback",
    [
        ("SentimentMomentumConservative", 0.7, 24),
        ("SentimentMomentumAggressive", 0.0, 72),
    ],
)
def test_build_brain_sentiment_momentum_variants(
    tmp_path, config_name: str, expected_floor: float, expected_lookback: int
):
    cfg = next(v for v in phase_4_variants() if v.name == config_name)
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert isinstance(brain, SentimentMomentumBrain)
    assert brain.name == config_name
    assert brain.uses_llm is False
    assert brain._credibility_floor == expected_floor
    assert brain._lookback_hours == expected_lookback


# ── build_brain rejects invalid combinations ────────────────────────────────


def test_build_brain_rejects_classical_with_llm_model(tmp_path):
    cfg = BrainVariantConfig(
        name="bad",
        strategy="classical",
        risk_profile="conservative",
        llm_model="claude-haiku-4-5-20251001",
    )
    with pytest.raises(ValueError, match="classical is deterministic"):
        build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)


def test_build_brain_rejects_sentiment_momentum_with_llm_model(tmp_path):
    cfg = BrainVariantConfig(
        name="bad",
        strategy="sentiment_momentum",
        risk_profile="conservative",
        llm_model="gpt-4o-mini",
    )
    with pytest.raises(ValueError, match="sentiment_momentum is deterministic"):
        build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)


def test_build_brain_rejects_sentiment_momentum_without_store():
    cfg = BrainVariantConfig(
        name="SentimentMomentumConservative",
        strategy="sentiment_momentum",
        risk_profile="conservative",
    )
    with pytest.raises(ValueError, match="sentiment_momentum strategy requires a Store"):
        build_brain(cfg, store=None, daily_budget_usd=1.0)


def test_build_brain_classical_does_not_require_store(tmp_path):
    """Classical is fully snapshot-driven; build_brain must accept store=None."""
    cfg = BrainVariantConfig(
        name="ClassicalAggressive",
        strategy="classical",
        risk_profile="aggressive",
    )
    brain = build_brain(cfg, store=None, daily_budget_usd=1.0)
    assert isinstance(brain, ClassicalBrain)


# ── variant_requires_store coverage ─────────────────────────────────────────


def test_variant_requires_store_for_sentiment_momentum():
    cfg = BrainVariantConfig(
        name="SentimentMomentumConservative",
        strategy="sentiment_momentum",
        risk_profile="conservative",
    )
    assert variant_requires_store(cfg) is True


def test_variant_requires_store_false_for_classical():
    cfg = BrainVariantConfig(
        name="ClassicalConservative",
        strategy="classical",
        risk_profile="conservative",
    )
    assert variant_requires_store(cfg) is False
