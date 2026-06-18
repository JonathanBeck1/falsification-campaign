"""Persistence-layer tests."""

from __future__ import annotations

from pathlib import Path

from trader.storage.store import Store


def test_store_initializes_schema(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    # Tables should exist; round-trip a tiny insert.
    store.save_snapshot("s1", "2026-05-18", "QQQ", {"foo": "bar"})
    snap = store.get_snapshot("s1")
    assert snap is not None
    assert snap["ticker"] == "QQQ"


def test_portfolio_init_and_update(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    pf = store.get_or_init_portfolio("BrainA", starting_cash=50_000)
    assert pf["cash"] == 50_000
    assert pf["position_qty"] == 0

    store.update_portfolio("BrainA", cash=40_000, position_qty=100, avg_cost=100, realized_pnl=0)
    pf2 = store.get_or_init_portfolio("BrainA", starting_cash=99_999)  # should ignore the seed now
    assert pf2["cash"] == 40_000
    assert pf2["position_qty"] == 100


def test_decision_round_trip(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.save_snapshot("s1", "2026-05-18", "QQQ", {})
    decision_id = store.save_decision(
        snapshot_id="s1",
        brain="ClassicalBrain",
        action="BUY",
        target_pct=1.0,
        confidence=0.8,
        reasoning="trend up",
        llm_cost_usd=0.0,
    )
    decisions = store.get_decisions_for_brain("ClassicalBrain")
    assert len(decisions) == 1
    assert decisions[0]["decision_id"] == decision_id
    assert decisions[0]["action"] == "BUY"


def test_llm_cost_today(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.record_llm_call(
        decision_id=None,
        brain="X",
        model="haiku",
        prompt_hash="abc",
        input_tokens=10,
        output_tokens=20,
        cached_tokens=0,
        cost_usd=0.5,
        latency_ms=100,
    )
    store.record_llm_call(
        decision_id=None,
        brain="X",
        model="haiku",
        prompt_hash="def",
        input_tokens=10,
        output_tokens=20,
        cached_tokens=0,
        cost_usd=0.25,
        latency_ms=100,
    )
    assert store.llm_cost_today() == 0.75


def test_event_logging(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.record_event("warn", "test", "something", {"k": "v"})
    # Just confirm no exception.
