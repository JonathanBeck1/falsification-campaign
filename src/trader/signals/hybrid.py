"""HybridBrain — LLM extracts strict feature labels, deterministic policy sizes.

Per `brain/10_llm_agent_boundaries.md`: LLMs do not make trade decisions.
Per `brain/20_llm_decision_boundary_adr.md`: the LLM emits a strict enum
schema (`LLMFeatures`); a versioned `SizingPolicy` consumes those labels
and produces the position. The policy version is the audit unit, not the LLM.

This brain also enforces two gates from `brain/20` drift 2 BEFORE issuing
the LLM call:

1. **Preventive cost gate** — if the daily LLM spend has hit the configured
   budget, fall back to the base classical decision and record why.
2. **Tier-1 deterministic short-circuit** — if the classical signal is
   already confident AND no breaking-urgency events have been observed in
   the recent lookback window, skip the LLM (saves spend on quiet days).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from trader.llm.client import LLMClient
from trader.llm.prompts.hybrid_v2 import SYSTEM_V2, format_user
from trader.signals.base import Decision
from trader.signals.classical import ClassicalBrain
from trader.signals.llm_features import LLMFeatures
from trader.signals.sizing_policy import SizingPolicy
from trader.storage.snapshot import DailySnapshot
from trader.storage.store import Store


class HybridBrain:
    uses_llm = True

    def __init__(
        self,
        llm: LLMClient | None = None,
        *,
        policy: SizingPolicy | None = None,
        store: Store | None = None,
        daily_budget_usd: float = 1.0,
        classical_confidence_threshold: float = 0.7,
        breaking_lookback_hours: int = 24,
        name: str = "HybridBrain",
    ) -> None:
        self.name = name
        self.llm = llm or LLMClient()
        self._classical = ClassicalBrain()
        self._policy = policy or SizingPolicy()
        self._store = store
        self._daily_budget_usd = daily_budget_usd
        self._classical_confidence_threshold = classical_confidence_threshold
        self._breaking_lookback_hours = breaking_lookback_hours

    def decide(self, snapshot: DailySnapshot) -> Decision:
        base = self._classical.decide(snapshot)

        if self._budget_exhausted():
            return self._fallback(base, "llm_budget_exhausted")

        if self._classical_short_circuit(base, snapshot):
            return self._fallback(base, "classical_decisive_no_breaking_news")

        resp = self.llm.complete(
            system=SYSTEM_V2,
            user=format_user(snapshot),
            response_format_json=True,
            max_tokens=256,
            temperature=0.0,
        )
        features = self._parse_features(resp.parsed, resp.content)

        final_action, target, notes = self._policy.size(base, features)
        reasoning = (
            f"{'; '.join(notes)} | sentiment={features.sentiment_label}"
            f" severity={features.severity_bucket} tags={features.event_tags}"
            f" | final target={target:.0%}"
        )

        severity_confidence = {"low": 0.9, "medium": 0.7, "high": 0.5, "breaking": 0.3}
        confidence = (base.confidence + severity_confidence[features.severity_bucket]) / 2

        return Decision(
            action=final_action,
            target_pct=target,
            confidence=confidence,
            reasoning=reasoning,
            llm_cost_usd=resp.cost_usd or 0.0,
            llm_model=resp.model,
            llm_prompt_hash=resp.prompt_hash,
            llm_input_tokens=resp.input_tokens,
            llm_output_tokens=resp.output_tokens,
            llm_cached_tokens=resp.cached_tokens,
            llm_latency_ms=resp.latency_ms,
        )

    def _budget_exhausted(self) -> bool:
        if self._store is None:
            return False
        return self._store.llm_cost_today() >= self._daily_budget_usd

    def _classical_short_circuit(self, base: Decision, snapshot: DailySnapshot) -> bool:
        if base.confidence < self._classical_confidence_threshold:
            return False
        if self._store is None:
            return False
        as_of = self._snapshot_time(snapshot)
        since = as_of - timedelta(hours=self._breaking_lookback_hours)
        return self._store.count_breaking_events_since(since, until=as_of) == 0

    def _fallback(self, base: Decision, reason: str) -> Decision:
        reasoning = (
            f"policy={self._policy.version}; base={base.action}@{base.target_pct:.0%};"
            f" llm_skipped={reason} | final target={base.target_pct:.0%}"
        )
        return Decision(
            action=base.action,
            target_pct=base.target_pct,
            confidence=base.confidence,
            reasoning=reasoning,
        )

    @staticmethod
    def _snapshot_time(snapshot: DailySnapshot) -> datetime:
        ts = snapshot.latest_bar.timestamp
        if ts.tzinfo is None or ts.utcoffset() is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    @staticmethod
    def _parse_features(parsed: object, content: str) -> LLMFeatures:
        payload = parsed
        if payload is None and content:
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict):
            return LLMFeatures.safe_default()
        try:
            return LLMFeatures.model_validate(payload)
        except ValidationError:
            return LLMFeatures.safe_default()
