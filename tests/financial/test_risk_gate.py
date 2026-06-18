"""Tests for the risk gate. This is the safety-critical module — be thorough."""

from __future__ import annotations

from pathlib import Path

import pytest

from trader.execution.risk import AccountState, RiskGate


def make_gate(tmp_path: Path, **overrides) -> RiskGate:
    kwargs = dict(
        max_position_pct=0.95,
        max_daily_loss_pct=0.03,
        kill_switch_path=tmp_path / ".kill_switch",
        max_llm_cost_per_day_usd=5.0,
    )
    kwargs.update(overrides)
    return RiskGate(**kwargs)


def acct(**overrides) -> AccountState:
    base = dict(
        cash=100_000.0,
        position_qty=0.0,
        avg_cost=0.0,
        equity_today=100_000.0,
        equity_session_start=100_000.0,
    )
    base.update(overrides)
    return AccountState(**base)


class TestTradingHalts:
    def test_kill_switch_halts_trading(self, tmp_path):
        gate = make_gate(tmp_path)
        (tmp_path / ".kill_switch").touch()
        halted, reason = gate.trading_halted(account=acct(), llm_cost_today_usd=0)
        assert halted
        assert "Kill switch" in reason

    def test_daily_loss_limit_halts_trading(self, tmp_path):
        gate = make_gate(tmp_path, max_daily_loss_pct=0.03)
        # 4% drawdown today
        halted, reason = gate.trading_halted(
            account=acct(equity_today=96_000.0),
            llm_cost_today_usd=0,
        )
        assert halted
        assert "Daily loss" in reason

    def test_at_loss_limit_exactly_halts(self, tmp_path):
        gate = make_gate(tmp_path, max_daily_loss_pct=0.03)
        halted, _ = gate.trading_halted(
            account=acct(equity_today=97_000.0),  # exactly -3%
            llm_cost_today_usd=0,
        )
        assert halted

    def test_just_under_loss_limit_does_not_halt(self, tmp_path):
        gate = make_gate(tmp_path, max_daily_loss_pct=0.03)
        halted, _ = gate.trading_halted(
            account=acct(equity_today=97_500.0),  # -2.5%
            llm_cost_today_usd=0,
        )
        assert not halted

    def test_llm_cost_cap_halts(self, tmp_path):
        gate = make_gate(tmp_path, max_llm_cost_per_day_usd=5.0)
        halted, reason = gate.trading_halted(account=acct(), llm_cost_today_usd=6.0)
        assert halted
        assert "LLM cost" in reason

    def test_no_halt_when_all_clear(self, tmp_path):
        gate = make_gate(tmp_path)
        halted, _ = gate.trading_halted(account=acct(), llm_cost_today_usd=0)
        assert not halted


class TestPositionSizing:
    def test_hold_passes_through(self, tmp_path):
        gate = make_gate(tmp_path)
        v = gate.review(
            proposed_action="HOLD",
            proposed_target_pct=0.0,
            last_price=100.0,
            account=acct(),
        )
        assert v.approved and v.final_action == "HOLD" and v.final_qty == 0

    def test_buy_to_full_position(self, tmp_path):
        gate = make_gate(tmp_path, max_position_pct=0.95)
        v = gate.review(
            proposed_action="BUY",
            proposed_target_pct=1.0,  # ask for 100%
            last_price=100.0,
            account=acct(),
        )
        # capped at 95% → 95000 / 100 = 950 shares
        assert v.approved
        assert v.final_action == "BUY"
        assert v.final_qty == 950
        assert "max_position_pct" in v.triggered_limits

    def test_buy_target_below_max(self, tmp_path):
        gate = make_gate(tmp_path, max_position_pct=0.95)
        v = gate.review(
            proposed_action="BUY",
            proposed_target_pct=0.5,
            last_price=100.0,
            account=acct(),
        )
        assert v.approved
        assert v.final_qty == 500
        assert "max_position_pct" not in v.triggered_limits

    def test_buy_with_insufficient_cash_downsizes(self, tmp_path):
        gate = make_gate(tmp_path)
        v = gate.review(
            proposed_action="BUY",
            proposed_target_pct=0.95,
            last_price=1000.0,
            account=acct(cash=500.0),
        )
        # would need way more cash; clips to 0 shares → reject as insufficient_cash
        assert not v.approved
        assert "insufficient_cash" in v.triggered_limits

    def test_buy_with_insufficient_cash_partial_fill(self, tmp_path):
        gate = make_gate(tmp_path)
        v = gate.review(
            proposed_action="BUY",
            proposed_target_pct=0.95,
            last_price=100.0,
            account=acct(cash=300.0, equity_today=100_000.0),
        )
        # would need 95000; cash=300; floors to 3 shares
        assert v.approved
        assert v.final_qty == 3
        assert "cash_clipped" in v.triggered_limits

    def test_buy_already_at_target_holds(self, tmp_path):
        gate = make_gate(tmp_path)
        # already 950 shares at $100 = 95k; target=95% on 100k equity → no delta
        v = gate.review(
            proposed_action="BUY",
            proposed_target_pct=0.95,
            last_price=100.0,
            account=acct(cash=5000.0, position_qty=950, equity_today=100_000.0),
        )
        assert v.approved and v.final_action == "HOLD"

    def test_sell_to_zero(self, tmp_path):
        gate = make_gate(tmp_path)
        v = gate.review(
            proposed_action="SELL",
            proposed_target_pct=0.0,
            last_price=100.0,
            account=acct(cash=0, position_qty=500, equity_today=50_000.0),
        )
        assert v.approved
        assert v.final_action == "SELL"
        assert v.final_qty == 500

    def test_sell_with_no_position_holds(self, tmp_path):
        gate = make_gate(tmp_path)
        v = gate.review(
            proposed_action="SELL",
            proposed_target_pct=0.0,
            last_price=100.0,
            account=acct(),
        )
        assert v.approved and v.final_action == "HOLD"

    def test_invalid_price_rejects(self, tmp_path):
        gate = make_gate(tmp_path)
        v = gate.review(
            proposed_action="BUY",
            proposed_target_pct=0.5,
            last_price=0.0,
            account=acct(),
        )
        assert not v.approved
        assert "invalid_price" in v.triggered_limits

    def test_target_pct_clipped_to_unit_interval(self, tmp_path):
        gate = make_gate(tmp_path, max_position_pct=1.0)
        v_over = gate.review(
            proposed_action="BUY",
            proposed_target_pct=1.5,
            last_price=100.0,
            account=acct(),
        )
        assert v_over.approved
        assert v_over.final_qty == 1000  # 100% of 100k @ $100

        v_neg = gate.review(
            proposed_action="BUY",
            proposed_target_pct=-0.5,
            last_price=100.0,
            account=acct(),
        )
        # clipped to 0 → already at 0 → HOLD
        assert v_neg.approved and v_neg.final_action == "HOLD"


class TestPDT:
    def test_pdt_blocks_4th_sell_under_25k(self, tmp_path):
        gate = make_gate(tmp_path, is_pdt_account=True)
        v = gate.review(
            proposed_action="SELL",
            proposed_target_pct=0.0,
            last_price=100.0,
            account=acct(
                cash=0,
                position_qty=100,
                equity_today=10_000.0,
                day_trades_last_5d=3,
            ),
        )
        assert not v.approved
        assert "pdt_cap" in v.triggered_limits

    def test_pdt_allows_normal_sell_above_25k(self, tmp_path):
        gate = make_gate(tmp_path, is_pdt_account=True)
        v = gate.review(
            proposed_action="SELL",
            proposed_target_pct=0.0,
            last_price=100.0,
            account=acct(
                cash=0,
                position_qty=300,
                equity_today=30_000.0,
                day_trades_last_5d=10,
            ),
        )
        assert v.approved


class TestInputValidation:
    def test_invalid_max_position_pct_raises(self, tmp_path):
        with pytest.raises(ValueError):
            RiskGate(
                max_position_pct=0.0,
                max_daily_loss_pct=0.03,
                kill_switch_path=tmp_path / ".kill_switch",
            )

    def test_invalid_max_daily_loss_pct_raises(self, tmp_path):
        with pytest.raises(ValueError):
            RiskGate(
                max_position_pct=0.95,
                max_daily_loss_pct=1.5,
                kill_switch_path=tmp_path / ".kill_switch",
            )
