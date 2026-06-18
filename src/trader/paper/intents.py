from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from trader.execution.risk import AccountState, RiskGate
from trader.research.event_candidates import EventCandidate

IntentDirection = Literal["bullish", "bearish"]
IntentAction = Literal["BUY", "SELL", "HOLD"]
IntentStatus = Literal["staged", "risk_blocked", "simulated", "skipped"]


@dataclass(frozen=True)
class PaperTradeIntent:
    event_id: str
    ticker: str
    direction: IntentDirection
    candidate_score: float
    confidence: float
    proposed_action: IntentAction
    proposed_target_pct: float
    risk_status: str
    risk_reason: str = ""
    final_action: IntentAction = "HOLD"
    final_qty: float = 0.0
    simulated_order_id: str = ""
    status: IntentStatus = "staged"
    source: str = ""
    event_type: str = ""
    title: str = ""
    intent_id: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.intent_id:
            object.__setattr__(self, "intent_id", str(uuid.uuid4()))
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(UTC))

    def with_updates(self, **updates) -> PaperTradeIntent:
        return replace(self, **updates)


def _clamp_pct(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def intent_from_candidate(
    candidate: EventCandidate,
    *,
    min_abs_score: float,
    long_target_pct: float,
    short_target_pct: float = 0.0,
) -> PaperTradeIntent | None:
    if candidate.direction == "neutral":
        return None
    if abs(candidate.score) < min_abs_score:
        return None

    if candidate.direction == "bullish":
        proposed_action: IntentAction = "BUY"
        proposed_target_pct = _clamp_pct(long_target_pct)
    else:
        proposed_action = "SELL"
        proposed_target_pct = _clamp_pct(short_target_pct)

    return PaperTradeIntent(
        event_id=candidate.event_id,
        ticker=candidate.ticker,
        direction=candidate.direction,
        candidate_score=float(candidate.score),
        confidence=float(candidate.confidence),
        proposed_action=proposed_action,
        proposed_target_pct=proposed_target_pct,
        risk_status="pending",
        source=candidate.source,
        event_type=candidate.event_type,
        title=candidate.title,
    )


def risk_review_intent(
    intent: PaperTradeIntent,
    *,
    risk_gate: RiskGate,
    account: AccountState,
    last_price: float,
) -> PaperTradeIntent:
    verdict = risk_gate.review(
        proposed_action=intent.proposed_action,
        proposed_target_pct=intent.proposed_target_pct,
        last_price=last_price,
        account=account,
    )
    risk_reason = verdict.reason
    if verdict.triggered_limits:
        risk_reason = f"{risk_reason}; limits={','.join(verdict.triggered_limits)}"

    if not verdict.approved:
        return intent.with_updates(
            risk_status="blocked",
            risk_reason=risk_reason,
            final_action="HOLD",
            final_qty=0.0,
            status="risk_blocked",
        )

    if verdict.final_action == "HOLD" or verdict.final_qty <= 0:
        return intent.with_updates(
            risk_status="approved_hold",
            risk_reason=risk_reason,
            final_action="HOLD",
            final_qty=0.0,
            status="skipped",
        )

    return intent.with_updates(
        risk_status="approved",
        risk_reason=risk_reason,
        final_action=verdict.final_action,
        final_qty=float(verdict.final_qty),
        status="staged",
    )
