"""Versioned deterministic policy that maps (base Decision, LLMFeatures) → size.

Per `brain/20_llm_decision_boundary_adr.md`, the policy — not the LLM — is the
audit unit. Bumping a threshold bumps the version. A backtest run links to a
specific `SizingPolicy.version`; replaying that run requires the same policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from trader.signals.base import Action, Decision
from trader.signals.llm_features import LLMFeatures

POLICY_VERSION = "hybrid-policy-v2"
# v2 fixes the abstention bug: severity caps and event-tag multipliers
# now apply even when LLM emits `abstain_reason` (previously short-
# circuited). Bumped per Codex re-review (2026-05-20) so historical
# `hybrid-policy-v1` runs are not silently re-interpreted under the new
# semantics — backtest replays must pin the policy version.


@dataclass(frozen=True)
class SizingPolicy:
    """Maps (base classical Decision, LLM-extracted features) → (target, notes).

    All multipliers are config, not literals. Any change here bumps `version`
    so the audit trail can distinguish runs."""

    version: str = POLICY_VERSION
    risk_off_multiplier: float = 0.5
    high_severity_cap: float = 0.5
    breaking_severity_cap: float = 0.3
    fomc_event_multiplier: float = 0.5

    def size(self, base: Decision, features: LLMFeatures) -> tuple[Action, float, list[str]]:
        notes: list[str] = [f"policy={self.version}", f"base={base.action}@{base.target_pct:.0%}"]
        target = base.target_pct

        # Abstention semantics (Codex adversarial review, 2026-05-20):
        # `abstain_reason` previously short-circuited the entire policy,
        # bypassing severity caps and event-tag risk reductions. That meant
        # an abstain LLM response with severity="breaking" or event=fomc
        # would skip the risk controls those features are supposed to
        # enforce. Fix: abstain skips ONLY sentiment handling (because the
        # LLM is explicitly saying it can't read the sentiment) while
        # severity caps and event-tag multipliers still apply. Parse
        # failures arrive here as abstain_reason="llm_response_unparseable"
        # with severity="low" via LLMFeatures.safe_default(), so they
        # naturally avoid the cap path.
        is_abstain = bool(features.abstain_reason)
        if is_abstain:
            notes.append(f"llm_abstain={features.abstain_reason}")

        if not is_abstain:
            if features.sentiment_label == "bearish" and base.action != "SELL":
                target *= self.risk_off_multiplier
                notes.append(f"sentiment=bearish → x{self.risk_off_multiplier}")
            elif features.sentiment_label == "bullish" and base.action == "BUY":
                notes.append("sentiment=bullish confirmed")

        if features.severity_bucket == "breaking":
            target = min(target, self.breaking_severity_cap)
            notes.append(f"severity=breaking → cap {self.breaking_severity_cap:.0%}")
        elif features.severity_bucket == "high":
            target = min(target, self.high_severity_cap)
            notes.append(f"severity=high → cap {self.high_severity_cap:.0%}")

        if "fomc" in features.event_tags:
            target *= self.fomc_event_multiplier
            notes.append(f"event=fomc → x{self.fomc_event_multiplier}")

        target = max(0.0, min(1.0, target))
        final_action = self._decide_action(base, target)
        return final_action, target, notes

    @staticmethod
    def _decide_action(base: Decision, target: float) -> Action:
        if target == 0:
            return "SELL"
        if target < base.target_pct:
            return "SELL"
        if base.action == "BUY":
            return "BUY"
        return base.action


# Phase 1 horse-race profiles. See brain/decisions/2026-05-21-horse-race-phase-1.md.
SIZING_POLICY_CONSERVATIVE = SizingPolicy(
    version="hybrid-policy-conservative-v1",
    risk_off_multiplier=0.3,
    high_severity_cap=0.3,
    breaking_severity_cap=0.15,
    fomc_event_multiplier=0.3,
)

SIZING_POLICY_AGGRESSIVE = SizingPolicy(
    version="hybrid-policy-aggressive-v1",
    risk_off_multiplier=0.7,
    high_severity_cap=0.7,
    breaking_severity_cap=0.5,
    fomc_event_multiplier=0.7,
)
