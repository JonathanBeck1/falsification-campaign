"""Phase 2 variant wiring: phase_2_variants, all_phase_variants, build_brain.

Per brain/decisions/2026-05-21-horse-race-phase-2.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trader.signals.macro_event import MacroEventBrain
from trader.signals.variants import (
    BrainVariantConfig,
    all_phase_variants,
    build_brain,
    phase_1_variants,
    phase_2_variants,
)
from trader.storage.store import Store


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "trader.sqlite")


def test_phase_2_variants_returns_two_unique_names():
    configs = phase_2_variants()
    assert len(configs) == 2
    names = {c.name for c in configs}
    assert names == {"MacroEventConservative", "MacroEventAggressive"}


def test_phase_2_variants_are_deterministic_macro_event():
    for c in phase_2_variants():
        assert c.strategy == "macro_event"
        assert c.llm_model is None
    assert {c.risk_profile for c in phase_2_variants()} == {"conservative", "aggressive"}


def test_all_phase_variants_combines_phases():
    phase1 = phase_1_variants()
    phase2 = phase_2_variants()
    combined = all_phase_variants()
    # Combined includes at least Phases 1+2 (later phases may extend it).
    assert len(combined) >= len(phase1) + len(phase2)
    combined_names = [v.name for v in combined]
    # Phase 1 names appear first, then Phase 2 — order matters for runner enumeration.
    assert combined_names[: len(phase1)] == [v.name for v in phase1]
    assert combined_names[len(phase1) : len(phase1) + len(phase2)] == [v.name for v in phase2]


def test_all_phase_variants_names_unique():
    names = [v.name for v in all_phase_variants()]
    assert len(set(names)) == len(names), f"variant names must be unique: {names}"


def test_build_brain_macro_event_conservative(tmp_path):
    cfg = BrainVariantConfig(
        name="MacroEventConservative", strategy="macro_event", risk_profile="conservative"
    )
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert isinstance(brain, MacroEventBrain)
    assert brain.name == "MacroEventConservative"
    assert brain.uses_llm is False
    assert brain._lookback_days == 90
    assert brain._require_multi_event_confirmation is True


def test_build_brain_macro_event_aggressive(tmp_path):
    cfg = BrainVariantConfig(
        name="MacroEventAggressive", strategy="macro_event", risk_profile="aggressive"
    )
    brain = build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)
    assert isinstance(brain, MacroEventBrain)
    assert brain.name == "MacroEventAggressive"
    assert brain._lookback_days == 14
    assert brain._require_multi_event_confirmation is False


def test_build_brain_rejects_macro_event_with_llm_model(tmp_path):
    cfg = BrainVariantConfig(
        name="bad",
        strategy="macro_event",
        risk_profile="conservative",
        llm_model="claude-haiku-4-5",
    )
    with pytest.raises(ValueError, match="macro_event is deterministic"):
        build_brain(cfg, store=_store(tmp_path), daily_budget_usd=1.0)


def test_build_brain_rejects_macro_event_without_store():
    cfg = BrainVariantConfig(
        name="MacroEventConservative", strategy="macro_event", risk_profile="conservative"
    )
    with pytest.raises(ValueError, match="macro_event strategy requires a Store"):
        build_brain(cfg, store=None, daily_budget_usd=1.0)
