"""Phase 3 variant wiring: phase_3_variants, all_phase_variants, build_brain.

Per brain/decisions/2026-05-21-horse-race-phase-3.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trader.signals.earnings_tone import (
    POLICY_AGGRESSIVE,
    POLICY_CONSERVATIVE,
    EarningsToneBrain,
)
from trader.signals.variants import (
    BrainVariantConfig,
    all_phase_variants,
    build_brain,
    phase_1_variants,
    phase_2_variants,
    phase_3_variants,
)
from trader.storage.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def test_phase_3_variants_returns_four_unique_names():
    configs = phase_3_variants()
    assert len(configs) == 4
    names = {c.name for c in configs}
    assert names == {
        "EarningsToneHaikuConservative",
        "EarningsToneHaikuAggressive",
        "EarningsToneGPT4oMiniConservative",
        "EarningsToneGPT4oMiniAggressive",
    }


def test_phase_3_variants_cover_full_matrix():
    configs = phase_3_variants()
    for c in configs:
        assert c.strategy == "earnings_tone"
        assert c.llm_model is not None
    assert {c.risk_profile for c in configs} == {"conservative", "aggressive"}
    assert {c.llm_model for c in configs} == {"claude-haiku-4-5-20251001", "gpt-4o-mini"}


def test_all_phase_variants_contains_phase_3_in_order():
    """Phase 3 variants appear in `all_phase_variants()` in the right slot,
    after Phase 1 and Phase 2. Later phases (4+) extend the tail; this test
    only pins Phase 3's position, not that it is the final phase."""
    phase1 = phase_1_variants()
    phase2 = phase_2_variants()
    phase3 = phase_3_variants()
    combined = all_phase_variants()
    assert len(combined) >= len(phase1) + len(phase2) + len(phase3)
    names = [v.name for v in combined]
    assert names[: len(phase1)] == [v.name for v in phase1]
    assert names[len(phase1) : len(phase1) + len(phase2)] == [v.name for v in phase2]
    p3_start = len(phase1) + len(phase2)
    p3_end = p3_start + len(phase3)
    assert names[p3_start:p3_end] == [v.name for v in phase3]


def test_all_phase_variants_names_unique():
    names = [v.name for v in all_phase_variants()]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize(
    "config_name,expected_model,expected_policy",
    [
        ("EarningsToneHaikuConservative", "claude-haiku-4-5-20251001", POLICY_CONSERVATIVE),
        ("EarningsToneHaikuAggressive", "claude-haiku-4-5-20251001", POLICY_AGGRESSIVE),
        ("EarningsToneGPT4oMiniConservative", "gpt-4o-mini", POLICY_CONSERVATIVE),
        ("EarningsToneGPT4oMiniAggressive", "gpt-4o-mini", POLICY_AGGRESSIVE),
    ],
)
def test_build_brain_earnings_tone_variants(tmp_path, config_name: str, expected_model: str, expected_policy):
    cfg = next(v for v in phase_3_variants() if v.name == config_name)
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert isinstance(brain, EarningsToneBrain)
    assert brain.name == config_name
    assert brain.uses_llm is True
    assert brain.llm.model == expected_model
    assert brain._policy is expected_policy


def test_conservative_uses_longer_lookback_and_higher_min_events(tmp_path):
    cfg = next(v for v in phase_3_variants() if v.name == "EarningsToneHaikuConservative")
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert brain._lookback_days == 30
    assert brain._min_events_for_signal == 3


def test_aggressive_uses_shorter_lookback_and_lower_min_events(tmp_path):
    cfg = next(v for v in phase_3_variants() if v.name == "EarningsToneHaikuAggressive")
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert brain._lookback_days == 14
    assert brain._min_events_for_signal == 1


def test_build_brain_rejects_earnings_tone_without_llm_model(tmp_path):
    cfg = BrainVariantConfig(
        name="bad", strategy="earnings_tone", risk_profile="conservative"
    )
    with pytest.raises(ValueError, match="earnings_tone strategy requires llm_model"):
        build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)


def test_build_brain_rejects_earnings_tone_without_store():
    cfg = BrainVariantConfig(
        name="EarningsToneHaikuConservative",
        strategy="earnings_tone",
        risk_profile="conservative",
        llm_model="claude-haiku-4-5-20251001",
    )
    with pytest.raises(ValueError, match="earnings_tone strategy requires a Store"):
        build_brain(cfg, store=None, daily_budget_usd=1.0)


def test_build_brain_rejects_earnings_tone_with_unsupported_model(tmp_path):
    cfg = BrainVariantConfig(
        name="EarningsToneFooConservative",
        strategy="earnings_tone",
        risk_profile="conservative",
        llm_model="some-other-model",
    )
    with pytest.raises(ValueError, match="does not support llm_model"):
        build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
