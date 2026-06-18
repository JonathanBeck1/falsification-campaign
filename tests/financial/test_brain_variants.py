"""Phase 1 horse-race: BrainVariantConfig + phase_1_variants + build_brain.

Validates that the 6 Phase-1 variants have distinct names, correct strategy
mappings, and produce concrete brain instances with matching `brain.name`
values. Per brain/decisions/2026-05-21-horse-race-phase-1.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trader.signals.hybrid import HybridBrain
from trader.signals.variants import (
    BrainVariantConfig,
    build_brain,
    max_position_pct_for_profile,
    phase_1_variants,
)
from trader.signals.vix_regime import VIXRegimeBrain
from trader.storage.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def test_phase_1_variants_returns_six_unique_names():
    configs = phase_1_variants()
    assert len(configs) == 6
    names = [c.name for c in configs]
    assert len(set(names)) == 6, f"variant names must be unique: {names}"


def test_phase_1_variants_cover_full_matrix():
    configs = phase_1_variants()
    by_strategy: dict[str, list[BrainVariantConfig]] = {}
    for c in configs:
        by_strategy.setdefault(c.strategy, []).append(c)

    # 2 VIXRegime variants (Conservative + Aggressive), 0 LLM
    vix = by_strategy["vix_regime"]
    assert len(vix) == 2
    assert {c.risk_profile for c in vix} == {"conservative", "aggressive"}
    assert all(c.llm_model is None for c in vix)

    # 4 Hybrid variants (2 LLM models x 2 risk profiles)
    hybrid = by_strategy["hybrid"]
    assert len(hybrid) == 4
    assert {c.risk_profile for c in hybrid} == {"conservative", "aggressive"}
    llm_models = {c.llm_model for c in hybrid}
    assert llm_models == {"claude-haiku-4-5-20251001", "gpt-4o-mini"}


def test_build_brain_vix_regime_conservative(tmp_path):
    cfg = BrainVariantConfig(name="VIXRegimeConservative", strategy="vix_regime", risk_profile="conservative")
    brain = build_brain(cfg, store=None, daily_budget_usd=1.0)
    assert isinstance(brain, VIXRegimeBrain)
    assert brain.name == "VIXRegimeConservative"
    assert brain.uses_llm is False


def test_build_brain_vix_regime_aggressive(tmp_path):
    cfg = BrainVariantConfig(name="VIXRegimeAggressive", strategy="vix_regime", risk_profile="aggressive")
    brain = build_brain(cfg, store=None, daily_budget_usd=1.0)
    assert isinstance(brain, VIXRegimeBrain)
    assert brain.name == "VIXRegimeAggressive"


def test_build_brain_hybrid_haiku_conservative(tmp_path):
    cfg = BrainVariantConfig(
        name="HybridHaikuConservative",
        strategy="hybrid",
        risk_profile="conservative",
        llm_model="claude-haiku-4-5-20251001",
    )
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert isinstance(brain, HybridBrain)
    assert brain.name == "HybridHaikuConservative"
    assert brain.uses_llm is True
    assert brain.llm.model == "claude-haiku-4-5-20251001"
    assert brain._policy.version == "hybrid-policy-conservative-v1"


def test_build_brain_hybrid_gpt4o_aggressive(tmp_path):
    cfg = BrainVariantConfig(
        name="HybridGPT4oMiniAggressive",
        strategy="hybrid",
        risk_profile="aggressive",
        llm_model="gpt-4o-mini",
    )
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert brain.llm.model == "gpt-4o-mini"
    assert brain._policy.version == "hybrid-policy-aggressive-v1"


def test_build_brain_rejects_vix_regime_with_llm_model():
    cfg = BrainVariantConfig(
        name="bad", strategy="vix_regime", risk_profile="conservative", llm_model="claude-haiku-4-5"
    )
    with pytest.raises(ValueError, match="vix_regime is deterministic"):
        build_brain(cfg, store=None, daily_budget_usd=1.0)


def test_build_brain_rejects_hybrid_without_llm_model():
    cfg = BrainVariantConfig(name="bad", strategy="hybrid", risk_profile="conservative")
    with pytest.raises(ValueError, match="hybrid strategy requires llm_model"):
        build_brain(cfg, store=None, daily_budget_usd=1.0)


def test_build_brain_rejects_hybrid_without_store():
    cfg = BrainVariantConfig(
        name="bad", strategy="hybrid", risk_profile="conservative", llm_model="claude-haiku-4-5"
    )
    with pytest.raises(ValueError, match="hybrid strategy requires a Store"):
        build_brain(cfg, store=None, daily_budget_usd=1.0)


def test_max_position_pct_for_profile_values():
    assert max_position_pct_for_profile("conservative") == 0.40
    assert max_position_pct_for_profile("aggressive") == 1.00
