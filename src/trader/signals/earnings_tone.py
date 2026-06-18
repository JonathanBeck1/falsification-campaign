"""EarningsToneBrain — top-10 QQQ 8-K aggregator with LLM tone extraction.

Reads SEC 8-K filings for `settings.sec_tickers` from `news_events`, sends
the bundle to the LLM in ONE call per cycle (not per filing), parses
`EarningsToneFeatures`, and applies a profile-specific
`EarningsTonePolicy` to convert labels → target_pct.

Per `brain/10_llm_agent_boundaries.md`: the LLM extracts structured
features only. The deterministic policy decides.

Per `brain/decisions/2026-05-21-horse-race-phase-3.md`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from trader.llm.client import LLMClient
from trader.llm.prompts.earnings_tone import SYSTEM_EARNINGS_TONE, format_user
from trader.signals.base import Decision
from trader.signals.earnings_tone_features import EarningsToneFeatures
from trader.storage.snapshot import DailySnapshot
from trader.storage.store import Store

SEC_SOURCE = "sec_edgar"
EARNINGS_EVENT_TYPES: frozenset[str] = frozenset(
    {"earnings_surprise", "guidance_raise", "guidance_lower"}
)


@dataclass(frozen=True)
class EarningsTonePolicy:
    """Versioned deterministic policy. Maps LLM features → target_pct."""

    version: str
    neutral_target: float
    bullish_target: float
    bearish_target: float
    require_high_confidence: bool
    require_majority_breadth: bool


POLICY_CONSERVATIVE = EarningsTonePolicy(
    version="earnings-tone-policy-conservative-v1",
    neutral_target=0.40,
    bullish_target=0.60,
    bearish_target=0.00,
    require_high_confidence=True,
    require_majority_breadth=True,
)

POLICY_AGGRESSIVE = EarningsTonePolicy(
    version="earnings-tone-policy-aggressive-v1",
    neutral_target=0.50,
    bullish_target=1.00,
    bearish_target=0.00,
    require_high_confidence=False,
    require_majority_breadth=False,
)


class EarningsToneBrain:
    """LLM-augmented earnings-tone brain. One LLM call per cycle per variant."""

    uses_llm = True

    def __init__(
        self,
        *,
        llm: LLMClient,
        store: Store,
        policy: EarningsTonePolicy,
        lookback_days: int,
        min_events_for_signal: int,
        name: str,
    ) -> None:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if min_events_for_signal < 1:
            raise ValueError("min_events_for_signal must be >= 1")
        for label, value in (
            ("neutral_target", policy.neutral_target),
            ("bullish_target", policy.bullish_target),
            ("bearish_target", policy.bearish_target),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be in [0, 1]")
        self.llm = llm
        self._store = store
        self._policy = policy
        self._lookback_days = lookback_days
        self._min_events_for_signal = min_events_for_signal
        self.name = name

    def decide(self, snapshot: DailySnapshot) -> Decision:
        now = _snapshot_time(snapshot)
        since = now - timedelta(days=self._lookback_days)

        events = [
            e
            for e in self._store.get_news_events_parsed(
                since=since,
                until=now + timedelta(microseconds=1),
                source=SEC_SOURCE,
                limit=10_000,
            )
            if e.source == SEC_SOURCE and e.event_type in EARNINGS_EVENT_TYPES
        ]

        if len(events) < self._min_events_for_signal:
            return Decision(
                action="HOLD",
                target_pct=self._policy.neutral_target,
                confidence=0.3,
                reasoning=(
                    f"no recent earnings 8-Ks ({len(events)} in last "
                    f"{self._lookback_days}d, need {self._min_events_for_signal})"
                ),
            )

        # ── LLM call (aggregator pattern: one call per cycle, not per event) ──
        resp = self.llm.complete(
            system=SYSTEM_EARNINGS_TONE,
            user=format_user(events),
            response_format_json=True,
            max_tokens=256,
        )

        try:
            payload = json.loads(resp.content)
        except json.JSONDecodeError as exc:
            return self._llm_error_fallback(f"json_decode: {exc}", resp)

        try:
            features = EarningsToneFeatures.model_validate(payload)
        except ValidationError as exc:
            return self._llm_error_fallback(f"schema_validation: {exc}", resp)

        action, target, notes = self._policy_size(features)
        return Decision(
            action=action,
            target_pct=target,
            confidence=0.7 if features.abstain_reason is None else 0.4,
            reasoning=(
                f"policy={self._policy.version}; "
                f"tone={features.aggregate_tone}, guidance={features.guidance_signal}, "
                f"breadth={features.breadth}, conf={features.confidence}; "
                f"{'; '.join(notes)}"
            ),
            llm_cost_usd=resp.cost_usd or 0.0,
            llm_model=resp.model,
            llm_prompt_hash=resp.prompt_hash,
            llm_input_tokens=resp.input_tokens,
            llm_output_tokens=resp.output_tokens,
            llm_cached_tokens=resp.cached_tokens,
            llm_latency_ms=resp.latency_ms,
        )

    # ── policy ────────────────────────────────────────────────────────────

    def _policy_size(
        self, features: EarningsToneFeatures
    ) -> tuple[str, float, list[str]]:
        notes: list[str] = []
        policy = self._policy

        if features.abstain_reason:
            notes.append(f"abstain={features.abstain_reason}")
            return "HOLD", policy.neutral_target, notes

        if policy.require_high_confidence and features.confidence != "high":
            notes.append(f"conf={features.confidence} < high (Conservative)")
            return "HOLD", policy.neutral_target, notes

        if policy.require_majority_breadth and features.breadth in {"split", "single_name_only"}:
            notes.append(f"breadth={features.breadth} (Conservative)")
            return "HOLD", policy.neutral_target, notes

        tone = features.aggregate_tone
        guidance = features.guidance_signal

        if tone == "bullish":
            if guidance == "lowered":
                notes.append("bullish_tone+lowered_guidance conflict -> HOLD")
                return "HOLD", policy.neutral_target, notes
            notes.append("bullish_tone -> BUY")
            return "BUY", policy.bullish_target, notes

        if tone == "bearish":
            if guidance == "raised":
                notes.append("bearish_tone+raised_guidance conflict -> HOLD")
                return "HOLD", policy.neutral_target, notes
            notes.append("bearish_tone -> SELL")
            return "SELL", policy.bearish_target, notes

        notes.append(f"tone={tone} -> HOLD")
        return "HOLD", policy.neutral_target, notes

    def _llm_error_fallback(self, reason: str, resp) -> Decision:
        return Decision(
            action="HOLD",
            target_pct=self._policy.neutral_target,
            confidence=0.3,
            reasoning=f"llm_error: {reason}",
            llm_cost_usd=resp.cost_usd or 0.0,
            llm_model=resp.model,
            llm_prompt_hash=resp.prompt_hash,
            llm_input_tokens=resp.input_tokens,
            llm_output_tokens=resp.output_tokens,
            llm_cached_tokens=resp.cached_tokens,
            llm_latency_ms=resp.latency_ms,
        )


def _snapshot_time(snapshot: DailySnapshot) -> datetime:
    ts = snapshot.latest_bar.timestamp
    if ts.tzinfo is None or ts.utcoffset() is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


# ── Factory helpers ────────────────────────────────────────────────────────


def earnings_tone_haiku_conservative(*, store: Store, daily_budget_usd: float = 1.0, name: str = "EarningsToneHaikuConservative") -> EarningsToneBrain:
    del daily_budget_usd  # Budget tracking lives in the cost gate, not this brain.
    return EarningsToneBrain(
        llm=LLMClient(model="claude-haiku-4-5-20251001"),
        store=store,
        policy=POLICY_CONSERVATIVE,
        lookback_days=30,
        min_events_for_signal=3,
        name=name,
    )


def earnings_tone_haiku_aggressive(*, store: Store, daily_budget_usd: float = 1.0, name: str = "EarningsToneHaikuAggressive") -> EarningsToneBrain:
    del daily_budget_usd
    return EarningsToneBrain(
        llm=LLMClient(model="claude-haiku-4-5-20251001"),
        store=store,
        policy=POLICY_AGGRESSIVE,
        lookback_days=14,
        min_events_for_signal=1,
        name=name,
    )


def earnings_tone_gpt4o_mini_conservative(*, store: Store, daily_budget_usd: float = 1.0, name: str = "EarningsToneGPT4oMiniConservative") -> EarningsToneBrain:
    del daily_budget_usd
    return EarningsToneBrain(
        llm=LLMClient(model="gpt-4o-mini"),
        store=store,
        policy=POLICY_CONSERVATIVE,
        lookback_days=30,
        min_events_for_signal=3,
        name=name,
    )


def earnings_tone_gpt4o_mini_aggressive(*, store: Store, daily_budget_usd: float = 1.0, name: str = "EarningsToneGPT4oMiniAggressive") -> EarningsToneBrain:
    del daily_budget_usd
    return EarningsToneBrain(
        llm=LLMClient(model="gpt-4o-mini"),
        store=store,
        policy=POLICY_AGGRESSIVE,
        lookback_days=14,
        min_events_for_signal=1,
        name=name,
    )
