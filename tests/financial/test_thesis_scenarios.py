"""End-to-end scenario tests.

Each scenario is a real-world news situation. The engine + aggregator
must produce a directional decision that matches the scenario's intent.
These are the "would this system actually work?" tests.
"""

from __future__ import annotations

import pytest

from trader.scenarios import SCENARIOS, build_scenario_events
from trader.thesis.aggregator import ThesisAggregator
from trader.thesis.engine import ThesisEngine


def _run_scenario(name: str):
    scenario = SCENARIOS[name]
    engine = ThesisEngine()
    aggregator = ThesisAggregator()
    events_with_times = build_scenario_events(scenario)

    theses = []
    final = None
    for event, observed in events_with_times:
        t = engine.classify(event)
        if t is not None:
            theses.append(t)
        final = aggregator.aggregate(theses, scenario.aggregate_inputs, now=observed)
    return final, theses


def test_fed_dovish_press_conference_ends_long():
    final, theses = _run_scenario("fed_dovish_press_conference")
    assert final is not None
    assert final.target_pct > 0.5, f"Expected long position, got {final.target_pct}"
    # Multiple fed_dovish_surprise theses should accumulate
    dovish_count = sum(1 for t in theses if t.template.bucket == "fed_dovish_surprise")
    assert dovish_count >= 1


def test_cpi_hot_surprise_ends_short():
    final, _ = _run_scenario("cpi_hot_surprise")
    assert final is not None
    assert final.target_pct < 0.5


def test_nvda_blowout_ends_long():
    final, theses = _run_scenario("nvda_blowout_earnings")
    assert final is not None
    assert final.target_pct > 0.5
    # Specifically the beat-and-raise bucket
    assert any(t.template.bucket == "megacap_earnings_beat_and_raise" for t in theses)


def test_aapl_guidance_cut_ends_short():
    final, theses = _run_scenario("aapl_guidance_cut")
    assert final is not None
    assert final.target_pct < 0.5
    assert any(t.template.bucket == "megacap_earnings_miss_or_cut" for t in theses)


def test_geopol_escalation_single_event_stays_pending():
    """A single-source geopolitical escalation must NOT move position —
    `geopol_escalation_major` has `confirmation_required=True`, so the
    thesis is constructed `pending` and excluded from `direction_sum`
    until a second source confirms.

    This test was previously named `..._first_event_short` and asserted
    `target_pct < 0.5` on the first event alone. Per Codex review
    (2026-05-20), that was a high-severity bug: single-source
    geopolitical rumors should not be tradeable. The corrected
    semantic — confirmation gating — is now pinned here.

    A follow-up PR that adds the confirmation-matching pass (incrementing
    `confirmed_sources` when a second source reports the same event)
    will flip these pending theses to confirmed and re-enable the short
    signal."""
    scenario = SCENARIOS["geopol_escalation"]
    engine = ThesisEngine()
    aggregator = ThesisAggregator()
    events_with_times = build_scenario_events(scenario)

    first_event, observed = events_with_times[0]
    t = engine.classify(first_event)
    assert t is not None
    assert t.template.bucket == "geopol_escalation_major"
    assert t.template.confirmation_required
    assert t.confirmation_state == "pending"

    decision = aggregator.aggregate([t], scenario.aggregate_inputs, now=observed)
    # Position stays at baseline; the pending thesis is surfaced but
    # excluded from sizing.
    assert decision.target_pct == decision.baseline_pct
    assert decision.direction_sum == 0
    assert t in decision.pending_confirmation_theses


def test_quiet_day_noise_stays_at_baseline():
    """All events in this scenario are in the IGNORE set. Target should
    remain at the baseline 0.5."""
    final, theses = _run_scenario("quiet_day_noise")
    assert final is not None
    assert final.target_pct == 0.5
    assert theses == [], "No theses should have been emitted"


def test_vix_stress_caps_bullish_signal():
    """Bullish news arriving during a high-VIX regime: even though the signal
    is bullish, the regime cap should limit total exposure."""
    final, _ = _run_scenario("vix_stress_with_bullish_news")
    assert final is not None
    # Cap is 0.5; target must not exceed it
    assert final.target_pct <= 0.5
    assert final.regime_cap < 1.0
    assert any("VIX" in r for r in final.regime_reasons)


@pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
def test_every_scenario_produces_a_valid_target(scenario_name):
    """Smoke test — every scenario must run end-to-end and produce a valid
    target_pct in [0, 1]."""
    final, _ = _run_scenario(scenario_name)
    assert final is not None
    assert 0.0 <= final.target_pct <= 1.0
