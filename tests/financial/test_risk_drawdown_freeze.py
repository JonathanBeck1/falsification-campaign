"""RiskGate drawdown-freeze tests (audit problem #13).

Verifies that an open position that's underwater by at least the
freeze threshold blocks further INCREASES but always allows exits.
"""

from __future__ import annotations

from pathlib import Path

from trader.execution.risk import AccountState, RiskGate


def _gate(*, freeze_pct: float = 0.05, tmp_path: Path | None = None) -> RiskGate:
    return RiskGate(
        max_position_pct=1.0,
        max_daily_loss_pct=0.03,
        kill_switch_path=tmp_path / ".kill" if tmp_path else Path("/tmp/_nonexistent"),
        freeze_after_drawdown_pct=freeze_pct,
    )


# ── Drawdown computation ──────────────────────────────────────────────────


def test_drawdown_pct_zero_when_no_position():
    acct = AccountState(
        cash=100_000, position_qty=0, avg_cost=0, equity_today=100_000, equity_session_start=100_000
    )
    assert acct.position_drawdown_pct(last_price=500.0) == 0.0


def test_drawdown_pct_positive_when_position_in_profit():
    acct = AccountState(
        cash=10_000,
        position_qty=100,
        avg_cost=400.0,
        equity_today=60_000,
        equity_session_start=50_000,
    )
    assert acct.position_drawdown_pct(last_price=500.0) == 0.25


def test_drawdown_pct_negative_when_position_underwater():
    acct = AccountState(
        cash=10_000,
        position_qty=100,
        avg_cost=500.0,
        equity_today=58_000,
        equity_session_start=60_000,
    )
    assert acct.position_drawdown_pct(last_price=480.0) == -0.04


def test_drawdown_pct_zero_when_invalid_avg_cost():
    """Guard against div-by-zero on a portfolio with stale avg_cost."""
    acct = AccountState(
        cash=10_000,
        position_qty=100,
        avg_cost=0.0,
        equity_today=58_000,
        equity_session_start=60_000,
    )
    assert acct.position_drawdown_pct(last_price=480.0) == 0.0


# ── Freeze blocks adds, allows exits ──────────────────────────────────────


def test_freeze_blocks_buy_when_position_down_more_than_threshold():
    """Position bought at $500, now $470 (-6%); freeze threshold 5%.
    BUY to increase should be refused; suggested action becomes HOLD."""
    gate = _gate(freeze_pct=0.05)
    acct = AccountState(
        cash=5_000,
        position_qty=100,
        avg_cost=500.0,
        equity_today=52_000,
        equity_session_start=55_000,
    )
    decision = gate.review(
        proposed_action="BUY",
        proposed_target_pct=1.0,  # try to increase further
        last_price=470.0,
        account=acct,
    )
    assert decision.final_action == "HOLD"
    assert decision.final_qty == 0.0
    assert "drawdown_freeze" in decision.triggered_limits
    assert "drawdown_freeze" in decision.reason


def test_freeze_does_not_block_at_exactly_threshold_minus_epsilon():
    """Just over the threshold should fire."""
    gate = _gate(freeze_pct=0.05)
    acct = AccountState(
        cash=5_000,
        position_qty=100,
        avg_cost=500.0,
        equity_today=52_000,
        equity_session_start=55_000,
    )
    # -5.01% drawdown: should fire
    decision = gate.review(
        proposed_action="BUY", proposed_target_pct=1.0, last_price=474.95, account=acct
    )
    assert "drawdown_freeze" in decision.triggered_limits


def test_freeze_does_not_fire_when_drawdown_within_threshold():
    """Position down 3%, threshold 5% — BUY is allowed."""
    gate = _gate(freeze_pct=0.05)
    acct = AccountState(
        cash=50_000,
        position_qty=50,
        avg_cost=500.0,
        equity_today=74_250,
        equity_session_start=75_000,
    )
    decision = gate.review(
        proposed_action="BUY", proposed_target_pct=1.0, last_price=485.0, account=acct
    )
    assert "drawdown_freeze" not in decision.triggered_limits


def test_freeze_allows_sell_to_exit_underwater_position():
    """Position is down 8%; brain wants to exit. Freeze MUST NOT block
    a SELL. The whole point of the rule is to STOP adding to losers,
    not to trap us in them."""
    gate = _gate(freeze_pct=0.05)
    acct = AccountState(
        cash=5_000,
        position_qty=100,
        avg_cost=500.0,
        equity_today=51_000,
        equity_session_start=55_000,
    )
    decision = gate.review(
        proposed_action="SELL",
        proposed_target_pct=0.0,
        last_price=460.0,
        account=acct,
    )
    # Sell-to-flat is approved
    assert decision.final_action == "SELL"
    assert "drawdown_freeze" not in decision.triggered_limits


def test_freeze_zero_setting_disables_check():
    """freeze_after_drawdown_pct=0.0 disables the rule entirely."""
    gate = _gate(freeze_pct=0.0)
    acct = AccountState(
        cash=5_000,
        position_qty=100,
        avg_cost=500.0,
        equity_today=42_000,  # massive drawdown
        equity_session_start=55_000,
    )
    decision = gate.review(
        proposed_action="BUY", proposed_target_pct=1.0, last_price=370.0, account=acct
    )
    assert "drawdown_freeze" not in decision.triggered_limits


def test_freeze_doesnt_fire_on_first_entry_no_position():
    """First trade of the day: no existing position, no drawdown. BUY
    must be allowed."""
    gate = _gate(freeze_pct=0.05)
    acct = AccountState(
        cash=100_000,
        position_qty=0,
        avg_cost=0,
        equity_today=100_000,
        equity_session_start=100_000,
    )
    decision = gate.review(
        proposed_action="BUY", proposed_target_pct=0.5, last_price=500.0, account=acct
    )
    assert "drawdown_freeze" not in decision.triggered_limits


def test_freeze_doesnt_fire_when_position_is_in_profit():
    """Up 10% — freeze rule should be silent."""
    gate = _gate(freeze_pct=0.05)
    acct = AccountState(
        cash=10_000,
        position_qty=100,
        avg_cost=500.0,
        equity_today=64_000,
        equity_session_start=60_000,
    )
    decision = gate.review(
        proposed_action="BUY", proposed_target_pct=1.0, last_price=550.0, account=acct
    )
    assert "drawdown_freeze" not in decision.triggered_limits


def test_freeze_init_rejects_negative_threshold():
    """Negative thresholds make no sense; constructor must reject."""
    import pytest

    with pytest.raises(ValueError, match="freeze_after_drawdown_pct"):
        RiskGate(
            max_position_pct=1.0,
            max_daily_loss_pct=0.03,
            kill_switch_path=Path("/tmp/_x"),
            freeze_after_drawdown_pct=-0.01,
        )
