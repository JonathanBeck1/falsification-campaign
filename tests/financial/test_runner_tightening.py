"""Runner behavior tests for auditability and risk-gate wiring."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

from trader import runner
from trader.signals.base import Decision
from trader.storage.snapshot import Bar, DailySnapshot, MacroSnapshot
from trader.storage.store import Store


class SilentNotifier:
    def send(self, title: str, body: str) -> None:
        pass


def make_snapshot(*, price: float = 100.0) -> DailySnapshot:
    bar = Bar(
        timestamp=datetime(2026, 5, 18, 20, 0, tzinfo=UTC),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1_000_000,
    )
    return DailySnapshot(
        snapshot_id="tightening-test",
        trade_date=date(2026, 5, 18),
        ticker="TEST",
        latest_bar=bar,
        recent_bars=[bar],
        sma_50=price,
        sma_200=price,
        rsi_14=50.0,
        realized_vol_20d=0.1,
        news=[],
        macro=MacroSnapshot(),
    )


def query_rows(path: Path, sql: str):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql).fetchall()]


def test_run_one_day_records_llm_audit_metadata(monkeypatch):
    class AuditBrain:
        # The test fakes the llm_* fields on the returned Decision; it does
        # not actually call an LLM at decide() time, so uses_llm stays False
        # (otherwise the freshness gate would skip it in the no-heartbeat test env).
        name = "AuditBrain"
        uses_llm = False

        def decide(self, snapshot):
            return Decision(
                action="HOLD",
                target_pct=0.0,
                confidence=0.8,
                reasoning="LLM extracted features only.",
                llm_cost_usd=0.07,
                llm_model="model-x",
                llm_prompt_hash="prompt123",
                llm_input_tokens=11,
                llm_output_tokens=13,
                llm_cached_tokens=2,
                llm_latency_ms=99,
            )

    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: [AuditBrain()])
    monkeypatch.setattr(runner, "build_notifier", lambda: SilentNotifier())

    runner.run_one_day(make_snapshot())

    rows = query_rows(Path("data/trader.sqlite"), "SELECT * FROM llm_calls")
    assert len(rows) == 1
    assert rows[0]["brain"] == "AuditBrain"
    assert rows[0]["model"] == "model-x"
    assert rows[0]["prompt_hash"] == "prompt123"
    assert rows[0]["input_tokens"] == 11
    assert rows[0]["output_tokens"] == 13
    assert rows[0]["cached_tokens"] == 2
    assert rows[0]["cost_usd"] == 0.07
    assert rows[0]["latency_ms"] == 99


def test_run_one_day_uses_prior_equity_for_daily_loss_halt(monkeypatch):
    class LossBrain:
        name = "LossBrain"
        uses_llm = False

        def decide(self, snapshot):
            return Decision("BUY", target_pct=1.0, confidence=0.9, reasoning="try to rebalance")

    store = Store(Path("data/trader.sqlite"))
    store.get_or_init_portfolio("LossBrain", starting_cash=100_000)
    store.update_portfolio("LossBrain", cash=0, position_qty=960, avg_cost=104.17, realized_pnl=0)
    store.record_equity("LossBrain", "2026-05-17", 100_000)

    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: [LossBrain()])
    monkeypatch.setattr(runner, "build_notifier", lambda: SilentNotifier())

    runner.run_one_day(make_snapshot(price=100.0))

    events = query_rows(Path("data/trader.sqlite"), "SELECT * FROM events WHERE level = 'kill'")
    assert len(events) == 1
    assert events[0]["source"] == "LossBrain"
    assert "Daily loss" in events[0]["message"]

    orders = query_rows(Path("data/trader.sqlite"), "SELECT * FROM orders")
    assert orders == []


def test_kill_switch_skips_brain_decide(monkeypatch):
    class HaltedBrain:
        name = "HaltedBrain"
        uses_llm = False

        def __init__(self):
            self.decide = Mock(side_effect=AssertionError("decide() must not run when halted"))

    brain = HaltedBrain()
    Path(".kill_switch").touch()
    try:
        monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: [brain])
        monkeypatch.setattr(runner, "build_notifier", lambda: SilentNotifier())

        runner.run_one_day(make_snapshot())

        brain.decide.assert_not_called()

        events = query_rows(Path("data/trader.sqlite"), "SELECT * FROM events WHERE level = 'kill'")
        assert len(events) >= 1
        assert any(e["source"] == "HaltedBrain" and "Kill switch present" in e["message"] for e in events)
    finally:
        Path(".kill_switch").unlink(missing_ok=True)


def test_post_llm_cost_halt_blocks_order_when_call_crosses_cap(monkeypatch, tmp_path):
    """Per Codex re-review (2026-05-20): the pre-decision halt catches
    'budget already exhausted' but cannot catch 'this decision's LLM
    call pushed us over.' Without a post-record_llm_call re-check, a
    brain whose call crosses the daily cap can still place an order
    because the halt was evaluated before the cost was recorded.

    This test seeds prior LLM spend just under the cap, then runs a
    brain whose decide() reports an llm_cost_usd that crosses it, and
    asserts no order was created."""

    class BudgetExceederBrain:
        name = "BudgetExceederBrain"
        uses_llm = True

        def decide(self, snapshot):
            return Decision(
                action="BUY",
                target_pct=1.0,
                confidence=0.9,
                reasoning="brain decided to BUY but this call crosses cap",
                llm_cost_usd=0.50,
                llm_model="test-model",
                llm_prompt_hash="hash_x",
                llm_input_tokens=100,
                llm_output_tokens=50,
                llm_cached_tokens=0,
                llm_latency_ms=10,
            )

    monkeypatch.setattr(runner, "all_brains", lambda settings, store=None: [BudgetExceederBrain()])
    monkeypatch.setattr(runner, "build_notifier", lambda: SilentNotifier())
    # The runner now skips LLM brains when the freshness gate trips
    # (Phase 1+ horse-race code generalized this to all uses_llm=True
    # brains). The test env has no heartbeat data so the gate would
    # short-circuit our LLM brain before it can decide. Mock the gate
    # to be permissive so we can exercise the post-LLM cost halt path.
    from trader.ingestion.heartbeat import FreshnessVerdict

    monkeypatch.setattr(
        runner,
        "gate_llm_brains_on_freshness",
        lambda _heartbeat: FreshnessVerdict(
            all_stale=False, stale_sources=(), fresh_sources=("test",), note=""
        ),
    )

    # Seed prior spend so the pre-decision halt does NOT fire (spend is
    # still under cap) but the post-record_llm_call check DOES (spend
    # crosses cap after recording the new call). RiskGate default cap
    # is $5/day, so prior $4.80 + new $0.50 = $5.30 crosses.
    from trader.storage.store import Store as TStore
    db_path = Path("data/trader.sqlite")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    seed_store = TStore(db_path)
    seed_store.record_llm_call(
        decision_id=None,
        brain="seed",
        model="seed-model",
        prompt_hash="seed_hash",
        input_tokens=100,
        output_tokens=100,
        cached_tokens=0,
        cost_usd=4.80,
        latency_ms=0,
    )

    runner.run_one_day(make_snapshot())

    orders = query_rows(db_path, "SELECT * FROM orders")
    # No order created — the post-LLM halt fired.
    assert orders == [], f"order was placed despite LLM-cost cap crossing: {orders}"

    events = query_rows(db_path, "SELECT * FROM events WHERE level = 'kill'")
    assert any(
        e["source"] == "BudgetExceederBrain" and "post-llm-cap" in e["message"]
        for e in events
    ), f"expected post-llm-cap kill event, got: {events}"
