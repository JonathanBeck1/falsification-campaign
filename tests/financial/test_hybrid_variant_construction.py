"""Hybrid variant construction wires SizingPolicy + thresholds + LLM correctly.

Per brain/decisions/2026-05-21-horse-race-phase-1.md the four Hybrid variants
must each get the right policy, the right risk-profile dial values, and the
right LLM model. Non-trivial because the variants are built via the
`build_brain` factory from BrainVariantConfig rows.
"""

from __future__ import annotations

from pathlib import Path

from trader.signals.sizing_policy import (
    SIZING_POLICY_AGGRESSIVE,
    SIZING_POLICY_CONSERVATIVE,
)
from trader.signals.variants import BrainVariantConfig, build_brain
from trader.storage.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def test_conservative_hybrid_uses_conservative_policy(tmp_path):
    brain = build_brain(
        BrainVariantConfig(
            name="HybridHaikuConservative",
            strategy="hybrid",
            risk_profile="conservative",
            llm_model="claude-haiku-4-5-20251001",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    assert brain._policy is SIZING_POLICY_CONSERVATIVE
    assert brain._policy.version == "hybrid-policy-conservative-v1"
    # Conservative cuts harder on bearish signals than the default v1 policy.
    assert brain._policy.risk_off_multiplier == 0.3
    assert brain._policy.high_severity_cap == 0.3
    assert brain._policy.breaking_severity_cap == 0.15
    assert brain._policy.fomc_event_multiplier == 0.3


def test_aggressive_hybrid_uses_aggressive_policy(tmp_path):
    brain = build_brain(
        BrainVariantConfig(
            name="HybridGPT4oMiniAggressive",
            strategy="hybrid",
            risk_profile="aggressive",
            llm_model="gpt-4o-mini",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    assert brain._policy is SIZING_POLICY_AGGRESSIVE
    assert brain._policy.version == "hybrid-policy-aggressive-v1"
    assert brain._policy.risk_off_multiplier == 0.7
    assert brain._policy.high_severity_cap == 0.7


def test_conservative_uses_higher_classical_confidence_threshold(tmp_path):
    brain = build_brain(
        BrainVariantConfig(
            name="HybridHaikuConservative",
            strategy="hybrid",
            risk_profile="conservative",
            llm_model="claude-haiku-4-5-20251001",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    # Conservative requires the classical base to be MORE confident before
    # consulting the LLM (saves LLM spend on quiet days).
    assert brain._classical_confidence_threshold == 0.85
    assert brain._breaking_lookback_hours == 48


def test_aggressive_uses_lower_classical_confidence_threshold(tmp_path):
    brain = build_brain(
        BrainVariantConfig(
            name="HybridHaikuAggressive",
            strategy="hybrid",
            risk_profile="aggressive",
            llm_model="claude-haiku-4-5-20251001",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    assert brain._classical_confidence_threshold == 0.55
    assert brain._breaking_lookback_hours == 12


def test_haiku_variant_passes_haiku_model_to_llm_client(tmp_path):
    brain = build_brain(
        BrainVariantConfig(
            name="HybridHaikuConservative",
            strategy="hybrid",
            risk_profile="conservative",
            llm_model="claude-haiku-4-5-20251001",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    assert brain.llm.model == "claude-haiku-4-5-20251001"


def test_gpt4o_mini_variant_passes_openai_model_to_llm_client(tmp_path):
    brain = build_brain(
        BrainVariantConfig(
            name="HybridGPT4oMiniAggressive",
            strategy="hybrid",
            risk_profile="aggressive",
            llm_model="gpt-4o-mini",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    assert brain.llm.model == "gpt-4o-mini"


def test_variant_name_threads_through_to_brain_name(tmp_path):
    cfg = BrainVariantConfig(
        name="HybridHaikuConservative",
        strategy="hybrid",
        risk_profile="conservative",
        llm_model="claude-haiku-4-5-20251001",
    )
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert brain.name == "HybridHaikuConservative"


def test_two_hybrid_variants_have_distinct_policies_objects(tmp_path):
    """Same brain class, different policy instances — must not share state."""
    conservative = build_brain(
        BrainVariantConfig(
            name="C",
            strategy="hybrid",
            risk_profile="conservative",
            llm_model="claude-haiku-4-5-20251001",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    aggressive = build_brain(
        BrainVariantConfig(
            name="A",
            strategy="hybrid",
            risk_profile="aggressive",
            llm_model="claude-haiku-4-5-20251001",
        ),
        store=_store(tmp_path),
        daily_budget_usd=1.0,
    )
    assert conservative._policy is not aggressive._policy
    assert conservative._policy.version != aggressive._policy.version
