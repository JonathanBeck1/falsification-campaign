"""Alpaca broker wrapper. Strict paper-vs-live separation. Idempotent orders.

In v0 every brain runs against the same Alpaca paper account by default, but each
brain also keeps a *virtual* per-brain portfolio in our SQLite (so we can score
brains against each other without splitting accounts). Use `SimBroker` for the
virtual side and `AlpacaBroker` for the one brain we wire to live execution.
"""

from __future__ import annotations

import contextlib
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import structlog

log = structlog.get_logger()

Side = Literal["buy", "sell"]

# Alpaca order statuses that mean "this order will not change again."
# Anything else is in-flight and worth polling. See:
# https://alpaca.markets/docs/api-references/trading-api/orders/#order-status
TERMINAL_ALPACA_STATUSES: frozenset[str] = frozenset(
    {"filled", "canceled", "cancelled", "expired", "rejected", "done_for_day", "replaced"}
)

# Per-lifecycle outcome the caller can branch on. "timeout_canceled" means we
# hit the wall clock with a non-terminal order and cancelled the remainder.
TerminalLifecycle = Literal[
    "filled",
    "partially_filled_canceled",
    "canceled",
    "expired",
    "rejected",
    "timeout_canceled",
    "submit_failed",
]


@dataclass(frozen=True)
class BrokerOrder:
    client_order_id: str
    ticker: str
    side: Side
    qty: float
    order_type: str = "market"
    limit_price: float | None = None


@dataclass(frozen=True)
class BrokerFill:
    client_order_id: str
    filled_qty: float
    filled_avg_price: float
    filled_at: datetime
    alpaca_order_id: str | None = None


@dataclass(frozen=True)
class OrderLifecycleResult:
    """The actual outcome of a submit + lifecycle-poll cycle.

    Used by callers who need to know what really happened (audit problem
    #14: partial-fill state mismatch). Treat `filled_qty` as the truth;
    NEVER assume the order filled at `submitted_qty`.
    """

    client_order_id: str
    alpaca_order_id: str | None
    terminal: TerminalLifecycle
    submitted_qty: float
    filled_qty: float
    filled_avg_price: float | None
    error: str | None = None

    @property
    def is_full_fill(self) -> bool:
        return self.terminal == "filled" and self.filled_qty >= self.submitted_qty

    @property
    def is_partial(self) -> bool:
        return 0 < self.filled_qty < self.submitted_qty

    @property
    def is_terminal_no_fill(self) -> bool:
        return self.filled_qty == 0 and self.terminal != "filled"


class Broker(Protocol):
    def submit(self, order: BrokerOrder) -> str: ...
    def positions(self) -> dict[str, float]: ...
    def cash(self) -> float: ...
    def equity(self) -> float: ...


# ──────────────────────────────────────────────────────────────────────────────
# SimBroker — per-brain virtual portfolio. No external calls.
# ──────────────────────────────────────────────────────────────────────────────


class SimBroker:
    """Updates a virtual portfolio stored in SQLite for one brain."""

    def __init__(self, brain: str, ticker: str, store, starting_cash: float, last_price: float) -> None:
        self.brain = brain
        self.ticker = ticker
        self.store = store
        self.last_price = last_price
        self.starting_cash = starting_cash
        self._pf = store.get_or_init_portfolio(brain, starting_cash)

    def cash(self) -> float:
        return float(self._pf["cash"])

    def position_qty(self) -> float:
        return float(self._pf["position_qty"])

    def avg_cost(self) -> float:
        return float(self._pf["avg_cost"])

    def equity(self) -> float:
        return self.cash() + self.position_qty() * self.last_price

    def fill_at_market(self, side: Side, qty: float, price: float, decision_id: str | None = None) -> BrokerFill:
        if qty <= 0:
            raise ValueError("qty must be positive")
        cash = self.cash()
        pos = self.position_qty()
        avg = self.avg_cost()
        realized = float(self._pf["realized_pnl"])

        if side == "buy":
            cost = qty * price
            if cost > cash:
                raise ValueError(f"insufficient cash: need {cost}, have {cash}")
            new_qty = pos + qty
            new_avg = ((pos * avg) + (qty * price)) / new_qty if new_qty > 0 else 0.0
            cash -= cost
            pos = new_qty
            avg = new_avg
        else:
            if qty > pos:
                raise ValueError(f"oversell: have {pos}, sell {qty}")
            realized += (price - avg) * qty
            cash += qty * price
            pos -= qty
            if pos == 0:
                avg = 0.0

        client_order_id = f"sim-{self.brain}-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        self.store.record_order(
            client_order_id=client_order_id,
            decision_id=decision_id,
            brain=self.brain,
            ticker=self.ticker,
            side=side,
            qty=qty,
            order_type="market",
            limit_price=None,
            alpaca_order_id=None,
        )
        self.store.update_order_status(client_order_id, "filled")
        self.store.record_fill(
            client_order_id=client_order_id,
            filled_qty=qty,
            filled_avg_price=price,
            filled_at=now.isoformat(),
        )
        self.store.update_portfolio(self.brain, cash, pos, avg, realized)
        self._pf = self.store.get_or_init_portfolio(self.brain, self.starting_cash)
        return BrokerFill(
            client_order_id=client_order_id,
            filled_qty=qty,
            filled_avg_price=price,
            filled_at=now,
        )


# ──────────────────────────────────────────────────────────────────────────────
# AlpacaBroker — real (paper or live) orders to Alpaca.
# ──────────────────────────────────────────────────────────────────────────────


class AlpacaBroker:
    def __init__(
        self,
        *,
        anti_herd_delay_range_s: tuple[float, float] = (0.0, 5.0),
        sleep_fn=None,
        rng=None,
    ) -> None:
        from alpaca.trading.client import TradingClient

        from trader.config import get_settings

        s = get_settings()
        self._paper = not s.trader_live
        self.client = TradingClient(
            s.alpaca_key_id,
            s.alpaca_secret_key,
            paper=self._paper,
        )
        # Anti-herd: random pre-submit delay decorrelates our orders from
        # any synchronized LLM-trading cohort hitting the same headline.
        # Default 0-5s; configurable via env, can be patched out in tests.
        env_max = os.environ.get("TRADER_ANTI_HERD_DELAY_MAX_S")
        if env_max is not None:
            with contextlib.suppress(ValueError):
                anti_herd_delay_range_s = (0.0, float(env_max))
        self._anti_herd_min_s, self._anti_herd_max_s = anti_herd_delay_range_s
        self._sleep = sleep_fn or time.sleep
        self._rng = rng or random.Random()

    @property
    def is_paper(self) -> bool:
        return self._paper

    def submit(self, order: BrokerOrder) -> str:
        """Submit a market order. Idempotent via client_order_id.

        Applies a small randomized pre-submit delay (anti-herd, per
        `brain/20` audit problem #5) so our order flow doesn't perfectly
        correlate with other systems reading the same headline.

        WARNING: Fire-and-forget. Does NOT poll for fill status, so partial
        fills and rejections silently propagate. For live trading, use
        `submit_with_lifecycle()` instead (audit problem #14).
        """
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        self._apply_anti_herd_delay()

        side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=order.ticker,
            qty=order.qty,
            side=side,
            time_in_force=TimeInForce.DAY,
            client_order_id=order.client_order_id,
        )
        resp = self.client.submit_order(req)
        return str(resp.id)

    def _apply_anti_herd_delay(self) -> None:
        lo, hi = self._anti_herd_min_s, self._anti_herd_max_s
        if hi <= 0 or hi <= lo:
            return
        self._sleep(self._rng.uniform(lo, hi))

    def submit_with_lifecycle(
        self,
        order: BrokerOrder,
        *,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
        sleep_fn=None,
    ) -> OrderLifecycleResult:
        """Submit, then poll until terminal status or timeout.

        Closes audit problem #14: callers always learn the actual fill
        quantity, not the assumption that the order filled at the
        submitted size. On timeout with a partial fill, the remainder is
        cancelled. On rejection, returns immediately with the error.

        `sleep_fn` lets tests inject a no-op sleeper.
        """
        sleep = sleep_fn or time.sleep
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        self._apply_anti_herd_delay()

        side = OrderSide.BUY if order.side == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=order.ticker,
            qty=order.qty,
            side=side,
            time_in_force=TimeInForce.DAY,
            client_order_id=order.client_order_id,
        )

        try:
            resp = self.client.submit_order(req)
        except Exception as exc:
            log.warning(
                "submit_with_lifecycle_submit_failed",
                client_order_id=order.client_order_id,
                error=str(exc),
            )
            return OrderLifecycleResult(
                client_order_id=order.client_order_id,
                alpaca_order_id=None,
                terminal="submit_failed",
                submitted_qty=order.qty,
                filled_qty=0.0,
                filled_avg_price=None,
                error=str(exc),
            )

        alpaca_order_id = str(getattr(resp, "id", None) or "")
        deadline = time.monotonic() + max(0.0, timeout_s)
        latest = resp
        while True:
            status = str(getattr(latest, "status", "") or "").lower()
            if status in TERMINAL_ALPACA_STATUSES:
                break
            if time.monotonic() >= deadline:
                break
            sleep(poll_interval_s)
            try:
                latest = self.client.get_order_by_id(alpaca_order_id)
            except Exception as exc:
                log.warning(
                    "submit_with_lifecycle_poll_failed",
                    client_order_id=order.client_order_id,
                    alpaca_order_id=alpaca_order_id,
                    error=str(exc),
                )
                break

        return self._finalize_lifecycle(order, alpaca_order_id, latest)

    def _finalize_lifecycle(
        self,
        order: BrokerOrder,
        alpaca_order_id: str,
        latest_order: object,
    ) -> OrderLifecycleResult:
        status = str(getattr(latest_order, "status", "") or "").lower()
        filled_qty = float(getattr(latest_order, "filled_qty", 0) or 0)
        filled_avg = getattr(latest_order, "filled_avg_price", None)
        filled_avg_price: float | None = float(filled_avg) if filled_avg is not None else None

        if status == "filled":
            return OrderLifecycleResult(
                client_order_id=order.client_order_id,
                alpaca_order_id=alpaca_order_id,
                terminal="filled",
                submitted_qty=order.qty,
                filled_qty=filled_qty if filled_qty > 0 else order.qty,
                filled_avg_price=filled_avg_price,
            )

        if status in {"canceled", "cancelled"}:
            return OrderLifecycleResult(
                client_order_id=order.client_order_id,
                alpaca_order_id=alpaca_order_id,
                terminal="canceled",
                submitted_qty=order.qty,
                filled_qty=filled_qty,
                filled_avg_price=filled_avg_price,
            )

        if status == "expired":
            return OrderLifecycleResult(
                client_order_id=order.client_order_id,
                alpaca_order_id=alpaca_order_id,
                terminal="expired",
                submitted_qty=order.qty,
                filled_qty=filled_qty,
                filled_avg_price=filled_avg_price,
            )

        if status == "rejected":
            reject_reason = (
                getattr(latest_order, "reject_reason", None)
                or getattr(latest_order, "failed_at", None)
                or "rejected_by_broker"
            )
            return OrderLifecycleResult(
                client_order_id=order.client_order_id,
                alpaca_order_id=alpaca_order_id,
                terminal="rejected",
                submitted_qty=order.qty,
                filled_qty=filled_qty,
                filled_avg_price=filled_avg_price,
                error=str(reject_reason),
            )

        # Non-terminal: hit the timeout. Cancel the remainder.
        try:
            self.client.cancel_order_by_id(alpaca_order_id)
        except Exception as exc:
            log.warning(
                "submit_with_lifecycle_cancel_failed",
                client_order_id=order.client_order_id,
                error=str(exc),
            )

        terminal: TerminalLifecycle = (
            "partially_filled_canceled" if filled_qty > 0 else "timeout_canceled"
        )

        return OrderLifecycleResult(
            client_order_id=order.client_order_id,
            alpaca_order_id=alpaca_order_id,
            terminal=terminal,
            submitted_qty=order.qty,
            filled_qty=filled_qty,
            filled_avg_price=filled_avg_price,
        )

    def positions(self) -> dict[str, float]:
        try:
            return {p.symbol: float(p.qty) for p in self.client.get_all_positions()}
        except Exception:
            return {}

    def cash(self) -> float:
        acct = self.client.get_account()
        return float(acct.cash)

    def equity(self) -> float:
        acct = self.client.get_account()
        return float(acct.equity)

    def market_is_open(self) -> bool:
        return self.market_status()[0]

    def market_status(self) -> tuple[bool, str]:
        """Returns (is_open, human_readable_reason). Per brain/external-repos
        research: callers want to log WHY a trade was skipped, not just
        a bool."""
        try:
            clk = self.client.get_clock()
        except Exception as exc:
            return False, f"clock_unavailable: {exc}"
        is_open = bool(clk.is_open)
        if is_open:
            return True, "open"
        next_open = getattr(clk, "next_open", None)
        next_close = getattr(clk, "next_close", None)
        if next_open and next_close:
            return False, f"closed; next_open={next_open.isoformat()}"
        return False, "closed"

    def cancel_all(self) -> None:
        self.client.cancel_orders()
