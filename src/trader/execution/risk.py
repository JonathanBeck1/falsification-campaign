"""Hard-coded risk limits. Sits between the brain and the broker.

The LLM does *not* get a vote on these. Every limit is enforced in plain Python.
If any limit fires, the order is blocked (or sized down) and an event is recorded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class RiskDecision:
    """Risk-gate verdict on a proposed action."""

    approved: bool
    final_action: Action
    final_qty: float
    reason: str
    triggered_limits: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccountState:
    cash: float
    position_qty: float
    avg_cost: float
    equity_today: float  # cash + position_qty * last_close
    equity_session_start: float  # equity at start of trading day
    day_trades_last_5d: int = 0

    def position_drawdown_pct(self, last_price: float) -> float:
        """How far the OPEN position is underwater vs its average entry,
        in percent (negative = losing). Returns 0.0 if no position or
        zero/invalid avg_cost. Used by the drawdown-freeze rule to
        block further adds to a losing position (audit problem #13)."""
        if self.position_qty <= 0 or self.avg_cost <= 0:
            return 0.0
        return (last_price - self.avg_cost) / self.avg_cost


class RiskGate:
    """Enforces all hard limits. One instance per process, reused across brains."""

    def __init__(
        self,
        *,
        max_position_pct: float,
        max_daily_loss_pct: float,
        kill_switch_path: Path,
        max_llm_cost_per_day_usd: float = 5.0,
        is_pdt_account: bool = True,
        # Audit problem #13: if the OPEN position is down by at least this
        # fraction vs its average entry, refuse to INCREASE the position.
        # Exits (SELL to reduce) are always allowed. Anti-spiral guard:
        # caps how much we can "average down" before sitting out a day.
        # 0.0 disables. Default 5% matches a standard hard stop.
        freeze_after_drawdown_pct: float = 0.05,
    ) -> None:
        if not 0 < max_position_pct <= 1.0:
            raise ValueError("max_position_pct must be in (0, 1]")
        if not 0 < max_daily_loss_pct <= 1.0:
            raise ValueError("max_daily_loss_pct must be in (0, 1]")
        if freeze_after_drawdown_pct < 0:
            raise ValueError("freeze_after_drawdown_pct must be >= 0")
        self.max_position_pct = max_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.kill_switch_path = kill_switch_path
        self.max_llm_cost_per_day_usd = max_llm_cost_per_day_usd
        self.is_pdt_account = is_pdt_account
        self.freeze_after_drawdown_pct = freeze_after_drawdown_pct

    # ── Pre-decision global checks ──────────────────────────────────────────
    def trading_halted(self, *, account: AccountState, llm_cost_today_usd: float) -> tuple[bool, str]:
        """Things that block *all* trading for the day, regardless of action."""
        if self.kill_switch_path.exists():
            return True, f"Kill switch present at {self.kill_switch_path}"
        if account.equity_session_start > 0:
            dd = (account.equity_today - account.equity_session_start) / account.equity_session_start
            if dd <= -self.max_daily_loss_pct:
                return True, f"Daily loss limit hit ({dd:.2%} <= -{self.max_daily_loss_pct:.2%})"
        if llm_cost_today_usd > self.max_llm_cost_per_day_usd:
            return True, (f"LLM cost cap exceeded (${llm_cost_today_usd:.2f} > ${self.max_llm_cost_per_day_usd:.2f})")
        return False, ""

    # ── Per-order sizing + approval ─────────────────────────────────────────
    def review(
        self,
        *,
        proposed_action: Action,
        proposed_target_pct: float,
        last_price: float,
        account: AccountState,
    ) -> RiskDecision:
        """Take a brain's proposal and return a sized + sanitized order.

        target_pct is desired *portfolio weight* in [0, 1]. We translate it to a
        share-quantity delta against current holdings, clipped by limits.
        """
        if proposed_action == "HOLD":
            return RiskDecision(True, "HOLD", 0.0, "Pass-through HOLD")

        if last_price <= 0:
            return RiskDecision(False, "HOLD", 0.0, "Invalid price", ("invalid_price",))

        if not 0 <= proposed_target_pct <= 1.0:
            proposed_target_pct = max(0.0, min(1.0, proposed_target_pct))

        triggered: list[str] = []

        # Cap target by max_position_pct
        capped_target_pct = min(proposed_target_pct, self.max_position_pct)
        if capped_target_pct < proposed_target_pct:
            triggered.append("max_position_pct")

        target_value = account.equity_today * capped_target_pct
        target_qty = math.floor(target_value / last_price)
        delta_qty = target_qty - account.position_qty

        # Drawdown freeze (audit problem #13): if the OPEN position is
        # underwater by >= the configured threshold, refuse to INCREASE
        # the position. Exits (delta < 0) are always allowed -- we don't
        # want to trap a brain that wants to cut a loss.
        if self.freeze_after_drawdown_pct > 0 and delta_qty > 0:
            dd_pct = account.position_drawdown_pct(last_price)
            if dd_pct <= -self.freeze_after_drawdown_pct:
                return RiskDecision(
                    True,
                    "HOLD",
                    0.0,
                    (
                        f"drawdown_freeze: position down {dd_pct:.2%} "
                        f"(threshold -{self.freeze_after_drawdown_pct:.2%}); "
                        f"refusing to increase"
                    ),
                    (*triggered, "drawdown_freeze"),
                )

        # Action sanity: if brain says BUY but delta is negative, override to HOLD.
        if proposed_action == "BUY" and delta_qty <= 0:
            return RiskDecision(True, "HOLD", 0.0, "Already at/above target weight", tuple(triggered))
        if proposed_action == "SELL" and delta_qty >= 0:
            # SELL with target ≥ current → interpret as "reduce to 0"
            delta_qty = -account.position_qty
            if delta_qty == 0:
                return RiskDecision(True, "HOLD", 0.0, "No position to sell", tuple(triggered))

        # Cash check on BUY
        if delta_qty > 0:
            cost = delta_qty * last_price
            if cost > account.cash:
                # downsize to whatever cash permits
                max_buyable = math.floor(account.cash / last_price)
                if max_buyable <= 0:
                    return RiskDecision(False, "HOLD", 0.0, "Insufficient cash", (*triggered, "insufficient_cash"))
                delta_qty = max_buyable
                triggered.append("cash_clipped")

        # PDT: under $25k accounts can't day-trade more than 3x in 5d.
        # We don't have full day-trade detection in v0; we simply refuse if the
        # account is PDT-restricted and equity is under $25k AND the order would
        # close a same-day position.
        if (
            self.is_pdt_account
            and account.equity_today < 25_000
            and proposed_action == "SELL"
            and account.day_trades_last_5d >= 3
        ):
            return RiskDecision(
                False,
                "HOLD",
                0.0,
                "PDT cap: 3 day-trades used in trailing 5d",
                (*triggered, "pdt_cap"),
            )

        final_action: Action = "BUY" if delta_qty > 0 else "SELL"
        return RiskDecision(
            approved=True,
            final_action=final_action,
            final_qty=abs(delta_qty),
            reason=(
                f"target {capped_target_pct:.0%}; delta {delta_qty} sh"
                + (f"; {','.join(triggered)}" if triggered else "")
            ),
            triggered_limits=tuple(triggered),
        )
