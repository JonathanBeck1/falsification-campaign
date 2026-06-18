"""Tests for AlpacaBroker.submit_with_lifecycle — partial-fill handling
and state-mismatch prevention (audit problem #14).

These tests stub out the Alpaca SDK so they're hermetic: no network.
The fake TradingClient lets us control the sequence of statuses that
get_order_by_id() returns, so we can simulate filled / partial /
rejected / timeout flows.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from trader.execution.broker import (
    AlpacaBroker,
    BrokerOrder,
    OrderLifecycleResult,
)


class _FakeOrder:
    """Minimal Order-like object exposing the attributes we read."""

    def __init__(
        self,
        *,
        order_id: str = "alpaca-order-1",
        status: str = "new",
        filled_qty: float = 0.0,
        filled_avg_price: float | None = None,
        reject_reason: str | None = None,
    ) -> None:
        self.id = order_id
        self.status = status
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price
        self.reject_reason = reject_reason


class _FakeTradingClient:
    """Returns a pre-seeded sequence of order states.

    `submit_order` returns the first state; `get_order_by_id` returns
    each subsequent state in order, sticking on the last one once
    exhausted. `cancel_order_by_id` is recorded for assertions.
    """

    def __init__(
        self,
        *,
        states: list[_FakeOrder],
        submit_raises: Exception | None = None,
        poll_raises: Exception | None = None,
    ) -> None:
        self._states = list(states)
        self._idx = 0
        self.submit_raises = submit_raises
        self.poll_raises = poll_raises
        self.cancelled: list[str] = []
        self.submit_count = 0
        self.poll_count = 0

    def submit_order(self, req):
        del req
        self.submit_count += 1
        if self.submit_raises is not None:
            raise self.submit_raises
        return self._states[0]

    def get_order_by_id(self, order_id):
        del order_id
        self.poll_count += 1
        if self.poll_raises is not None:
            raise self.poll_raises
        self._idx = min(self._idx + 1, len(self._states) - 1)
        return self._states[self._idx]

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled.append(order_id)


def _broker_with_client(client: _FakeTradingClient, monkeypatch) -> AlpacaBroker:
    """Build an AlpacaBroker with the SDK TradingClient patched out."""

    class _StubTradingClient:
        def __new__(cls, *args, **kwargs):
            del args, kwargs
            return client

    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "s")
    monkeypatch.setattr("alpaca.trading.client.TradingClient", _StubTradingClient)
    from trader.config import get_settings

    get_settings.cache_clear()
    broker = AlpacaBroker()
    get_settings.cache_clear()
    return broker


def _order(qty: float = 100) -> BrokerOrder:
    return BrokerOrder(client_order_id="coid-1", ticker="SPY", side="buy", qty=qty)


def _noop_sleep(_seconds: float) -> None:
    return None


# ── Happy path ─────────────────────────────────────────────────────────────


def test_full_fill_returns_filled_terminal(monkeypatch):
    """Submit returns 'new', first poll returns 'filled' with full qty."""
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="filled", filled_qty=100, filled_avg_price=500.0),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(_order(qty=100), sleep_fn=_noop_sleep)

    assert isinstance(result, OrderLifecycleResult)
    assert result.terminal == "filled"
    assert result.is_full_fill
    assert result.filled_qty == 100
    assert result.filled_avg_price == 500.0
    assert client.cancelled == []  # nothing to cancel


def test_filled_immediately_on_submit_doesnt_poll(monkeypatch):
    """If submit returns a filled order, no polling needed."""
    client = _FakeTradingClient(
        states=[_FakeOrder(status="filled", filled_qty=100, filled_avg_price=500.0)]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(_order(), sleep_fn=_noop_sleep)

    assert result.terminal == "filled"
    assert client.poll_count == 0


# ── Partial fill ───────────────────────────────────────────────────────────


def test_partial_fill_at_timeout_cancels_remainder(monkeypatch):
    """Order partially fills and stays partially_filled past the timeout.
    Broker cancels the remainder. filled_qty is the actual partial."""
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="partially_filled", filled_qty=40, filled_avg_price=499.5),
            _FakeOrder(status="partially_filled", filled_qty=40, filled_avg_price=499.5),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(qty=100),
        timeout_s=0.001,  # immediate timeout
        poll_interval_s=0.0,
        sleep_fn=_noop_sleep,
    )

    assert result.terminal == "partially_filled_canceled"
    assert result.is_partial
    assert result.filled_qty == 40
    assert result.submitted_qty == 100
    assert client.cancelled == ["alpaca-order-1"]


def test_partial_then_filled_returns_filled(monkeypatch):
    """Order partially fills, then completes within timeout. Terminal=filled."""
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="partially_filled", filled_qty=40, filled_avg_price=499.5),
            _FakeOrder(status="filled", filled_qty=100, filled_avg_price=499.7),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(qty=100), timeout_s=10.0, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )

    assert result.terminal == "filled"
    assert result.filled_qty == 100
    assert client.cancelled == []  # filled before timeout


# ── Rejection / cancellation ───────────────────────────────────────────────


def test_rejected_order_returns_rejected_with_reason(monkeypatch):
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="rejected", reject_reason="insufficient_buying_power"),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(), timeout_s=1.0, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )

    assert result.terminal == "rejected"
    assert result.filled_qty == 0
    assert result.is_terminal_no_fill
    assert "insufficient_buying_power" in (result.error or "")
    assert client.cancelled == []  # broker already cancelled it


def test_canceled_by_broker_returns_canceled_terminal(monkeypatch):
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="canceled", filled_qty=0),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(), timeout_s=1.0, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )

    assert result.terminal == "canceled"
    assert result.filled_qty == 0


def test_expired_order_returns_expired_terminal(monkeypatch):
    client = _FakeTradingClient(states=[_FakeOrder(status="expired")])
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(), timeout_s=1.0, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )
    assert result.terminal == "expired"


# ── Timeout with no fill ───────────────────────────────────────────────────


def test_timeout_with_no_fill_cancels_and_returns_timeout_canceled(monkeypatch):
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="accepted"),
            _FakeOrder(status="accepted"),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(qty=100), timeout_s=0.001, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )

    assert result.terminal == "timeout_canceled"
    assert result.filled_qty == 0
    assert client.cancelled == ["alpaca-order-1"]


# ── Submit failures ────────────────────────────────────────────────────────


def test_submit_raises_returns_submit_failed(monkeypatch):
    """If submit_order raises, the broker returns submit_failed with error
    detail. Does NOT crash the caller."""
    client = _FakeTradingClient(
        states=[_FakeOrder(status="new")],
        submit_raises=RuntimeError("rate limit"),
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(_order(), sleep_fn=_noop_sleep)

    assert result.terminal == "submit_failed"
    assert result.filled_qty == 0
    assert result.alpaca_order_id is None
    assert "rate limit" in (result.error or "")


def test_poll_failure_returns_best_known_state(monkeypatch):
    """If get_order_by_id raises mid-polling, fall back to the last-known
    order state rather than crashing."""
    client = _FakeTradingClient(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="partially_filled", filled_qty=30, filled_avg_price=499.0),
        ],
        poll_raises=ConnectionError("network blip"),
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(qty=100), timeout_s=1.0, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )

    # We never saw a terminal status; treat as timeout-cancel
    assert result.terminal in {"timeout_canceled", "partially_filled_canceled"}


# ── Cancel failure during timeout ──────────────────────────────────────────


def test_cancel_failure_doesnt_crash(monkeypatch):
    """If cancel_order_by_id raises on the timeout path, broker logs and
    returns the result with whatever fill data it has."""

    class _ClientWithCancelFailure(_FakeTradingClient):
        def cancel_order_by_id(self, order_id: str) -> None:
            super().cancel_order_by_id(order_id)
            raise RuntimeError("cancel api 5xx")

    client = _ClientWithCancelFailure(
        states=[
            _FakeOrder(status="new"),
            _FakeOrder(status="partially_filled", filled_qty=20, filled_avg_price=500.0),
        ]
    )
    broker = _broker_with_client(client, monkeypatch)
    result = broker.submit_with_lifecycle(
        _order(qty=100), timeout_s=0.001, poll_interval_s=0.0, sleep_fn=_noop_sleep
    )

    assert result.filled_qty == 20
    assert result.terminal == "partially_filled_canceled"
    assert "alpaca-order-1" in client.cancelled


# ── Properties / dataclass shape ───────────────────────────────────────────


def test_lifecycle_result_properties():
    """Spot-check is_full_fill / is_partial / is_terminal_no_fill."""
    full = OrderLifecycleResult(
        client_order_id="x",
        alpaca_order_id="y",
        terminal="filled",
        submitted_qty=10,
        filled_qty=10,
        filled_avg_price=100.0,
    )
    assert full.is_full_fill
    assert not full.is_partial
    assert not full.is_terminal_no_fill

    partial = OrderLifecycleResult(
        client_order_id="x",
        alpaca_order_id="y",
        terminal="partially_filled_canceled",
        submitted_qty=10,
        filled_qty=4,
        filled_avg_price=100.0,
    )
    assert not partial.is_full_fill
    assert partial.is_partial

    none = OrderLifecycleResult(
        client_order_id="x",
        alpaca_order_id="y",
        terminal="rejected",
        submitted_qty=10,
        filled_qty=0,
        filled_avg_price=None,
    )
    assert none.is_terminal_no_fill


def test_alpaca_status_alias_cancelled_accepted(monkeypatch):
    """Both 'canceled' and 'cancelled' spellings should map to canceled."""
    for spelling in ("canceled", "cancelled"):
        client = _FakeTradingClient(states=[_FakeOrder(status=spelling)])
        broker = _broker_with_client(client, monkeypatch)
        result = broker.submit_with_lifecycle(
            _order(), timeout_s=0.001, poll_interval_s=0.0, sleep_fn=_noop_sleep
        )
        assert result.terminal == "canceled", f"spelling={spelling}"


# ── Backward-compat: submit() still works ──────────────────────────────────


def test_submit_method_still_returns_order_id(monkeypatch):
    """Pre-existing `submit()` callers shouldn't break."""
    client = _FakeTradingClient(states=[_FakeOrder(status="new")])
    broker = _broker_with_client(client, monkeypatch)
    order_id = broker.submit(_order())
    assert order_id == "alpaca-order-1"


# Silence the unused-import warning under some test discovery modes.
_ = SimpleNamespace
_ = pytest
