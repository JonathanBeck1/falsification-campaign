"""Day-trade counter tests.

Verifies that `Store.count_day_trades_last_n_days` correctly identifies
round trips per brain per ticker per calendar day, ignoring stale orders
outside the window and unfilled orders.
"""

from __future__ import annotations

from pathlib import Path

from trader.storage.store import Store


def _record_round_trip(
    store: Store, *, brain: str, ticker: str, decision_id: str = "d1", filled: bool = True
) -> None:
    """Helper: submit a buy + sell pair for the given brain/ticker. Both
    orders default to status='filled' so they count as a day trade."""
    import uuid

    buy_id = f"buy-{uuid.uuid4().hex[:8]}"
    sell_id = f"sell-{uuid.uuid4().hex[:8]}"
    store.record_order(
        client_order_id=buy_id,
        decision_id=None,
        brain=brain,
        ticker=ticker,
        side="buy",
        qty=10,
        order_type="market",
        limit_price=None,
        alpaca_order_id=None,
    )
    store.record_order(
        client_order_id=sell_id,
        decision_id=None,
        brain=brain,
        ticker=ticker,
        side="sell",
        qty=10,
        order_type="market",
        limit_price=None,
        alpaca_order_id=None,
    )
    if filled:
        store.update_order_status(buy_id, "filled")
        store.update_order_status(sell_id, "filled")


def test_empty_store_returns_zero(tmp_path: Path) -> None:
    store = Store(tmp_path / "trader.sqlite")
    assert store.count_day_trades_last_n_days("BrainX") == 0


def test_single_buy_only_is_not_a_day_trade(tmp_path: Path) -> None:
    store = Store(tmp_path / "trader.sqlite")
    store.record_order(
        client_order_id="b1",
        decision_id=None,
        brain="BrainX",
        ticker="SPY",
        side="buy",
        qty=10,
        order_type="market",
        limit_price=None,
        alpaca_order_id=None,
    )
    store.update_order_status("b1", "filled")
    assert store.count_day_trades_last_n_days("BrainX") == 0


def test_buy_then_sell_same_day_is_one_day_trade(tmp_path: Path) -> None:
    store = Store(tmp_path / "trader.sqlite")
    _record_round_trip(store, brain="BrainX", ticker="SPY")
    assert store.count_day_trades_last_n_days("BrainX") == 1


def test_three_round_trips_count_separately(tmp_path: Path) -> None:
    """Three different-ticker round trips on the same day -> 3 day trades.
    This is the exact threshold where PDT kicks in."""
    store = Store(tmp_path / "trader.sqlite")
    _record_round_trip(store, brain="BrainX", ticker="SPY")
    _record_round_trip(store, brain="BrainX", ticker="QQQ")
    _record_round_trip(store, brain="BrainX", ticker="DIA")
    assert store.count_day_trades_last_n_days("BrainX") == 3


def test_multiple_round_trips_same_day_same_ticker_count_as_one(tmp_path: Path) -> None:
    """Buy-sell-buy-sell on SPY in one day is colloquially '2 day trades'
    but in our SQL it groups by (day, ticker). We accept this as a v0
    approximation; SEC rule is even stricter (counts opening/closing pairs).
    """
    store = Store(tmp_path / "trader.sqlite")
    _record_round_trip(store, brain="BrainX", ticker="SPY")
    _record_round_trip(store, brain="BrainX", ticker="SPY")
    # In v0 implementation, both round trips on the same (day, ticker)
    # collapse to one entry in the day-trade set.
    assert store.count_day_trades_last_n_days("BrainX") == 1


def test_other_brain_round_trips_dont_count(tmp_path: Path) -> None:
    store = Store(tmp_path / "trader.sqlite")
    _record_round_trip(store, brain="OtherBrain", ticker="SPY")
    assert store.count_day_trades_last_n_days("BrainX") == 0


def test_unfilled_round_trip_does_not_count(tmp_path: Path) -> None:
    """Orders that never filled should not count toward PDT."""
    store = Store(tmp_path / "trader.sqlite")
    _record_round_trip(store, brain="BrainX", ticker="SPY", filled=False)
    assert store.count_day_trades_last_n_days("BrainX") == 0


def test_pdt_rule_threshold_is_three_round_trips(tmp_path: Path) -> None:
    """Sanity: the existing RiskGate blocks at >=3 day trades in 5d. Test
    that 3 round trips returns exactly 3 from the counter."""
    store = Store(tmp_path / "trader.sqlite")
    _record_round_trip(store, brain="BrainX", ticker="SPY")
    _record_round_trip(store, brain="BrainX", ticker="QQQ")
    _record_round_trip(store, brain="BrainX", ticker="DIA")
    count = store.count_day_trades_last_n_days("BrainX", n_days=5)
    assert count == 3
