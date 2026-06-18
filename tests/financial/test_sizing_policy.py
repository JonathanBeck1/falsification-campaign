"""SizingPolicy mapping tests.

The policy is the audit unit. These tests pin its behavior so a threshold
change without a version bump fails CI.
"""

from __future__ import annotations

from trader.signals.base import Decision
from trader.signals.llm_features import LLMFeatures
from trader.signals.sizing_policy import POLICY_VERSION, SizingPolicy


def _base(action="BUY", target_pct=1.0) -> Decision:
    return Decision(action=action, target_pct=target_pct, confidence=0.6, reasoning="base")


def _features(sentiment="neutral", severity="low", tags=None, abstain=None) -> LLMFeatures:
    return LLMFeatures(
        sentiment_label=sentiment,
        severity_bucket=severity,
        event_tags=tags or ["none"],
        abstain_reason=abstain,
    )


def test_policy_version_pinned_at_v2():
    """Bumping POLICY_VERSION should be a conscious commit; pinning it here.

    v2 (this branch) fixes the abstention bug: severity caps and
    event-tag multipliers now apply even when LLM emits
    `abstain_reason`. v1 short-circuited the entire policy on abstain.
    Bump per Codex re-review (2026-05-20) so historical runs are not
    silently re-interpreted under different semantics."""
    assert POLICY_VERSION == "hybrid-policy-v2"
    assert SizingPolicy().version == "hybrid-policy-v2"


def test_neutral_features_pass_base_through_unchanged():
    action, target, notes = SizingPolicy().size(_base(), _features())
    assert action == "BUY"
    assert target == 1.0
    assert notes[0].startswith("policy=hybrid-policy-v2")


def test_bearish_sentiment_halves_long_position():
    action, target, _ = SizingPolicy().size(_base("BUY", 1.0), _features(sentiment="bearish"))
    assert target == 0.5
    assert action == "SELL"  # target dropped below base


def test_bearish_does_not_amplify_existing_sell():
    """When base already says SELL, bearish sentiment should not double-trim."""
    base = _base("SELL", 0.3)
    _, target, _ = SizingPolicy().size(base, _features(sentiment="bearish"))
    assert target == 0.3


def test_high_severity_caps_target():
    _, target, notes = SizingPolicy().size(_base("BUY", 1.0), _features(severity="high"))
    assert target == 0.5
    assert any("severity=high" in n for n in notes)


def test_breaking_severity_caps_lower_than_high():
    _, target, _ = SizingPolicy().size(_base("BUY", 1.0), _features(severity="breaking"))
    assert target == 0.3


def test_fomc_tag_halves_exposure():
    _, target, notes = SizingPolicy().size(_base("BUY", 1.0), _features(tags=["fomc"]))
    assert target == 0.5
    assert any("event=fomc" in n for n in notes)


def test_compound_bearish_high_severity_fomc_floors_correctly():
    """Bearish (0.5) -> high severity cap (0.5) -> fomc (x0.5). 1.0 -> 0.5 -> cap 0.5 -> 0.25."""
    _, target, _ = SizingPolicy().size(
        _base("BUY", 1.0),
        _features(sentiment="bearish", severity="high", tags=["fomc"]),
    )
    assert target == 0.25


def test_abstain_skips_sentiment_but_still_applies_severity_cap():
    """Per Codex adversarial review (2026-05-20): abstain previously
    short-circuited the entire policy, bypassing severity caps and
    event-tag multipliers. Corrected semantic: abstain skips ONLY
    sentiment handling — severity and event risk reductions still apply.
    abstain + severity=high should cap at 0.5, not pass 1.0 through."""
    base = _base("BUY", 1.0)
    action, target, notes = SizingPolicy().size(
        base, _features(sentiment="bearish", severity="high", abstain="ambiguous_news")
    )
    assert target == 0.5
    assert not any("sentiment=bearish" in n for n in notes)
    assert any("severity=high" in n for n in notes)
    assert any("llm_abstain=ambiguous_news" in n for n in notes)
    assert action == "SELL"  # target 0.5 < base 1.0


def test_abstain_with_low_severity_passes_base_through():
    """Abstain + severity=low (parse-failure path via safe_default).
    Base passes through unchanged, no caps."""
    base = _base("BUY", 1.0)
    action, target, _ = SizingPolicy().size(
        base, _features(severity="low", abstain="llm_response_unparseable")
    )
    assert action == "BUY"
    assert target == 1.0


def test_abstain_with_breaking_severity_caps_at_30pct():
    """The dangerous case Codex flagged: abstain + breaking severity.
    The cap MUST apply or we're full-sized into an event the LLM
    couldn't read."""
    base = _base("BUY", 1.0)
    _, target, _ = SizingPolicy().size(
        base, _features(severity="breaking", abstain="prompt_injection_suspected")
    )
    assert target == 0.3


def test_abstain_with_fomc_tag_still_halves():
    """Abstain + event=fomc: even if we can't read sentiment, FOMC
    risk reduction still applies."""
    base = _base("BUY", 1.0)
    _, target, _ = SizingPolicy().size(
        base, _features(tags=["fomc"], abstain="conflicting_signals")
    )
    assert target == 0.5


def test_abstain_compound_severity_and_fomc():
    """Abstain + breaking severity + fomc tag: cap THEN fomc multiplier.
    1.0 -> cap 0.3 -> x0.5 fomc = 0.15."""
    base = _base("BUY", 1.0)
    _, target, _ = SizingPolicy().size(
        base, _features(severity="breaking", tags=["fomc"], abstain="ambiguous"),
    )
    assert target == 0.15


def test_target_clamped_to_unit_interval():
    """Defensive: even with weird base, output stays in [0, 1]."""
    _, target, _ = SizingPolicy().size(_base("BUY", 1.5), _features())
    assert 0.0 <= target <= 1.0
    _, target, _ = SizingPolicy().size(_base("BUY", -0.5), _features())
    assert 0.0 <= target <= 1.0


def test_policy_is_deterministic_for_same_inputs():
    """Same (base, features) → same (action, target). No randomness."""
    base = _base("BUY", 1.0)
    feats = _features(sentiment="bullish", severity="medium", tags=["earnings"])
    out1 = SizingPolicy().size(base, feats)
    out2 = SizingPolicy().size(base, feats)
    assert out1 == out2


def test_version_string_appears_in_notes_for_audit():
    _, _, notes = SizingPolicy(version="hybrid-policy-v2-test").size(_base(), _features())
    assert any("policy=hybrid-policy-v2-test" in n for n in notes)
