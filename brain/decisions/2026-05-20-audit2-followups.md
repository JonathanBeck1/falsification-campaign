# Audit 2 Follow-ups: Bracket OCO + Corporate-Action IGNORE Note

Date: 2026-05-20
Status: design notes for items that cannot be safely fixed without
hitting the live Alpaca API. PR #35 closes the fixable items from the
second-batch audit (problems #11-#16). This doc captures what's left
and exactly how it should be implemented when we wire live trading.
Owner: the maintainer (via Claude Code).

## Status of the second-batch audit

PR #35 addresses:

- **#11 Corporate actions** (mostly N/A for SPY/QQQ; doc note below)
- **#13 Averaging-down spiral**: `freeze_after_drawdown_pct` parameter
  on RiskGate (default 5%) refuses to INCREASE an open position that's
  down by ≥ the threshold. Exits are always allowed.
- **#14 Partial fills / state mismatch**: new
  `AlpacaBroker.submit_with_lifecycle()` polls until terminal status,
  cancels partial fills at timeout, returns the actual fill quantity
  as the truth.
- **#12 Context bloat**, **#15 concurrent races**, **#16 tool-calling
  failures**: already structurally solved by our architecture per the
  audit conversation.

PR #36 (stacks on PR #33) will add `max_target_change_per_cycle` to
ThesisAggregator — the second half of the anti-spiral protection.

## What's left: bracket OCO orders (audit #13, partial fix)

### Why this is deferred

A "real" stop-loss must live at the broker, not in our Python loop.
Stops in code don't fire when your laptop loses internet or the runner
crashes. The right pattern is Alpaca's `OrderClass.BRACKET` — an
atomic 3-leg order (entry + stop-loss + take-profit) where the stop
and target are GTC orders that live on Alpaca's side until one fills,
at which point the other auto-cancels (OCO).

This cannot be safely built without testing against the actual Alpaca
paper API. The risk:

- Bracket orders behave differently for buys vs sells, for stocks vs
  options, and have specific rules about when they can be modified
  vs only cancelled-and-replaced.
- Wrong stop placement (e.g., too tight, gap risk) can produce
  catastrophic losses on the open.
- Alpaca's `LimitOrderRequest` vs `MarketOrderRequest` vs
  `StopLossRequest` interplay is provider-specific and changes between
  SDK versions.

So this lands when we have an Alpaca paper account and can test against
real fills.

### Implementation spec (for when we wire live)

#### API surface

```python
# src/trader/execution/broker.py (additions)

@dataclass(frozen=True)
class BracketOrder:
    """A 3-leg bracket order. Entry is a market order; the stop_loss and
    take_profit are GTC orders that activate after the entry fills.
    OCO: when one of stop/target fires, the other auto-cancels."""

    client_order_id: str
    ticker: str
    side: Side
    qty: float
    stop_loss_price: float           # absolute, not pct
    take_profit_price: float | None  # None to skip TP leg

class AlpacaBroker:
    def submit_bracket(
        self,
        order: BracketOrder,
        *,
        timeout_s: float = 30.0,
    ) -> OrderLifecycleResult:
        """Submit a bracket order. Entry leg is the parent; stop/target
        legs are children. Returns when entry leg reaches a terminal
        state; the child legs live on Alpaca until one fires."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        req = MarketOrderRequest(
            symbol=order.ticker,
            qty=order.qty,
            side=OrderSide.BUY if order.side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,  # NOT DAY -- children must outlive the session
            order_class=OrderClass.BRACKET,
            client_order_id=order.client_order_id,
            stop_loss=StopLossRequest(stop_price=order.stop_loss_price),
            take_profit=(
                TakeProfitRequest(limit_price=order.take_profit_price)
                if order.take_profit_price is not None
                else None
            ),
        )
        # ... reuse the submit_with_lifecycle polling skeleton for the parent
```

#### Wiring into the trade path

The runner currently calls `SimBroker.fill_at_market(...)`. The live
path will call `AlpacaBroker.submit_bracket(...)` with:

- `stop_loss_price = entry_price * (1 - freeze_after_drawdown_pct)` —
  same threshold as the in-process drawdown freeze, but enforced at
  the broker
- `take_profit_price` = optionally derived from
  `ThesisTemplate.expected_magnitude_pct` (PR #30); we may also leave
  this None and let the `horizon_minutes` time-stop handle exits

When the entry leg fills, two events fire:

1. The position is opened — our SimBroker portfolio updates
2. The stop and target legs sit on Alpaca as live orders

We need to add:

- A `reconcile_bracket_state()` method that queries open child orders
  and reconciles them against our SimBroker state. Run at the start
  of every cycle.
- A way to detect "stop fired" — query Alpaca for filled child orders;
  if a stop filled, flag the ticker as FROZEN for the rest of the
  session (matches the audit's recommendation).

#### Test strategy

Same pattern as PR #35's `test_alpaca_broker_lifecycle.py`: stub the
TradingClient, simulate the parent/child status sequence, assert the
broker correctly identifies entry-filled / stop-filled / target-filled
states.

For paper-trading integration tests (once we have the key wired):

- Submit a SPY bracket buy with stop $5 below entry and target $10
  above
- Verify the parent fills
- Verify the child legs appear in `get_orders()`
- Cancel the children manually
- Re-submit, watch the stop trigger when SPY drops (or simulate by
  setting a tight stop)

#### When to land this

After the first live paper-trading session. Until then, the
**in-process drawdown freeze from PR #35 is the safety net**. It's
not as good as a real stop (it only fires when the runner is alive),
but it's better than nothing and it's testable.

## Corporate-action IGNORE note (audit #11, doc-only)

`brain/21_news_to_trade_thesis_algorithm.md` already excludes most
corporate-action news from the thesis taxonomy by event-type routing.
There's no `corporate_action_*` bucket in `THESIS_TABLE`, so:

- Split announcements fall through to "other" → IGNORE
- Special dividend announcements fall through to "other" → IGNORE
- Symbol changes (e.g., FB → META) fall through to "other" → IGNORE
- Spinoffs fall through to "other" → IGNORE

The structural protection is:

1. We trade SPY/QQQ, not single names. Single-name corporate actions
   don't affect us mechanically.
2. Alpaca's bar data is split-adjusted. We can't see a "10x overnight
   gain" because the adjustment happens on Alpaca's side.
3. The `news_events.classified_at` timestamp and PIT discipline in
   `brain/19`/`brain/08` mean we can replay historical events with
   the correct adjustment state.

**The risk that remains**: when [brain/22](brain/22)'s tier-1 data
sources land (specifically the QQQ-megacap earnings calendar), a
megacap with an impending corporate action (NVDA's 10:1 split,
AAPL's special dividend) could *secondarily* shift news sentiment in
our enricher.

**Recommended mitigation when megacap-aware code lands**:

- Add a `corporate_action_calendar` adapter (similar shape to the
  economic-calendar adapter proposed in brain/22)
- For each megacap with an upcoming split/dividend in the next 7
  days, flag related events as `corporate_action_adjacent` and route
  them to IGNORE
- Surface the flag on the dashboard so a human can see what was
  filtered

This is a follow-up to the brain/22 tier-1 data work, not a
standalone PR. Adding the flag in code today (without the calendar
adapter to populate it) would just leave a dangling field.

## Summary

| Audit problem | Status | Where |
|---|---|---|
| #11 Corporate actions | 🟢 Structurally safe for SPY/QQQ; doc note above for megacap expansion | This doc |
| #12 Context bloat | 🟢 Solved by architecture | (no work needed) |
| #13 Averaging down — partial fix | 🟢 `freeze_after_drawdown_pct` in RiskGate | PR #35 |
| #13 Averaging down — pacing | 🟡 `max_target_change_per_cycle` deferred | PR #36 (next) |
| #13 Averaging down — real stops | 🟡 Bracket OCO deferred to live work | This doc, spec above |
| #14 Partial fills | 🟢 `submit_with_lifecycle()` | PR #35 |
| #15 Concurrent races | 🟢 N/A | architecture |
| #16 Tool-calling format | 🟢 Solved by architecture | architecture |

After PRs #35 and #36, the only meaningfully open item from this audit
is bracket OCO — and that's correctly gated on live-account access.
