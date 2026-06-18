from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trader.execution.risk import AccountState, RiskGate
from trader.paper.intents import PaperTradeIntent, intent_from_candidate, risk_review_intent
from trader.research.event_candidates import EventCandidate
from trader.storage.store import Store


def _intent(**overrides) -> PaperTradeIntent:
    data = {
        "intent_id": "intent-1",
        "event_id": "event-1",
        "created_at": datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        "ticker": "AAPL",
        "direction": "bullish",
        "candidate_score": 72.5,
        "confidence": 0.81,
        "proposed_action": "BUY",
        "proposed_target_pct": 0.25,
        "risk_status": "pending",
        "risk_reason": "",
        "final_action": "HOLD",
        "final_qty": 0.0,
        "simulated_order_id": "",
        "status": "staged",
        "source": "demo_news",
        "event_type": "guidance_raise",
        "title": "Apple raises guidance",
    }
    data.update(overrides)
    return PaperTradeIntent(**data)


def _candidate(**overrides) -> EventCandidate:
    data = {
        "event_id": "event-1",
        "published_at": datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        "source": "demo_news",
        "title": "Apple raises guidance",
        "ticker": "AAPL",
        "direction": "bullish",
        "score": 72.5,
        "confidence": 0.81,
        "is_actionable": True,
        "event_type": "guidance_raise",
        "urgency": "high",
        "reasons": ["sentiment=+0.7"],
        "key_claims": ["Apple raised guidance"],
    }
    data.update(overrides)
    return EventCandidate(**data)


def test_paper_trade_intent_store_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    intent = _intent()

    store.save_paper_trade_intent(intent)

    rows = store.list_paper_trade_intents(limit=5)
    assert rows == [
        {
            "intent_id": "intent-1",
            "event_id": "event-1",
            "created_at": "2026-05-21T12:00:00+00:00",
            "ticker": "AAPL",
            "direction": "bullish",
            "candidate_score": 72.5,
            "confidence": 0.81,
            "proposed_action": "BUY",
            "proposed_target_pct": 0.25,
            "risk_status": "pending",
            "risk_reason": "",
            "final_action": "HOLD",
            "final_qty": 0.0,
            "simulated_order_id": "",
            "status": "staged",
            "source": "demo_news",
            "event_type": "guidance_raise",
            "title": "Apple raises guidance",
        }
    ]


def test_update_paper_trade_intent_status(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_paper_trade_intent(_intent())

    store.update_paper_trade_intent_status("intent-1", "simulated", simulated_order_id="sim-1")

    row = store.list_paper_trade_intents(limit=1)[0]
    assert row["status"] == "simulated"
    assert row["simulated_order_id"] == "sim-1"


def test_update_paper_trade_intent_status_rejects_unknown_status(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_paper_trade_intent(_intent())

    with pytest.raises(ValueError, match="Unsupported paper trade intent status"):
        store.update_paper_trade_intent_status("intent-1", "bad")


def test_intent_from_bullish_candidate_stages_buy():
    intent = intent_from_candidate(
        _candidate(direction="bullish", score=72.5),
        min_abs_score=60,
        long_target_pct=1.5,
    )

    assert intent is not None
    assert intent.event_id == "event-1"
    assert intent.ticker == "AAPL"
    assert intent.direction == "bullish"
    assert intent.proposed_action == "BUY"
    assert intent.proposed_target_pct == 1.0
    assert intent.risk_status == "pending"
    assert intent.status == "staged"
    assert intent.source == "demo_news"
    assert intent.event_type == "guidance_raise"
    assert intent.title == "Apple raises guidance"


def test_intent_from_bearish_candidate_stages_sell_to_short_target():
    intent = intent_from_candidate(
        _candidate(direction="bearish", score=-88.0),
        min_abs_score=60,
        long_target_pct=0.4,
        short_target_pct=-0.5,
    )

    assert intent is not None
    assert intent.direction == "bearish"
    assert intent.proposed_action == "SELL"
    assert intent.proposed_target_pct == 0.0


def test_intent_from_candidate_ignores_neutral_or_low_score():
    assert intent_from_candidate(_candidate(direction="neutral", score=0.0), min_abs_score=10, long_target_pct=0.2) is None
    assert (
        intent_from_candidate(_candidate(direction="bullish", score=59.9), min_abs_score=60, long_target_pct=0.2)
        is None
    )


def _risk_gate(tmp_path: Path) -> RiskGate:
    return RiskGate(max_position_pct=0.95, max_daily_loss_pct=0.03, kill_switch_path=tmp_path / ".kill")


def _account(**overrides) -> AccountState:
    data = {
        "cash": 100_000.0,
        "position_qty": 0.0,
        "avg_cost": 0.0,
        "equity_today": 100_000.0,
        "equity_session_start": 100_000.0,
        "day_trades_last_5d": 0,
    }
    data.update(overrides)
    return AccountState(**data)


def test_risk_review_intent_approves_actionable_buy(tmp_path: Path):
    reviewed = risk_review_intent(
        _intent(proposed_action="BUY", proposed_target_pct=0.25),
        risk_gate=_risk_gate(tmp_path),
        account=_account(),
        last_price=100.0,
    )

    assert reviewed.risk_status == "approved"
    assert reviewed.status == "staged"
    assert reviewed.final_action == "BUY"
    assert reviewed.final_qty == 250
    assert "target 25%" in reviewed.risk_reason


def test_risk_review_intent_blocks_failed_risk_verdict(tmp_path: Path):
    reviewed = risk_review_intent(
        _intent(proposed_action="BUY", proposed_target_pct=0.25),
        risk_gate=_risk_gate(tmp_path),
        account=_account(),
        last_price=0.0,
    )

    assert reviewed.risk_status == "blocked"
    assert reviewed.status == "risk_blocked"
    assert reviewed.final_action == "HOLD"
    assert reviewed.final_qty == 0
    assert "Invalid price" in reviewed.risk_reason
    assert "invalid_price" in reviewed.risk_reason


def test_risk_review_intent_marks_approved_hold_when_risk_gate_approves_no_order(tmp_path: Path):
    reviewed = risk_review_intent(
        _intent(proposed_action="BUY", proposed_target_pct=0.25),
        risk_gate=_risk_gate(tmp_path),
        account=_account(position_qty=300.0, avg_cost=100.0),
        last_price=100.0,
    )

    assert reviewed.risk_status == "approved_hold"
    assert reviewed.status == "skipped"
    assert reviewed.final_action == "HOLD"
    assert reviewed.final_qty == 0
    assert "Already at/above target weight" in reviewed.risk_reason
