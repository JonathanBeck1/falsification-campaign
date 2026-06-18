"""Tests for AlpacaBroker's anti-herd delay + market_status helpers.

Anti-herd: the broker sleeps a random 0-5s before submitting an order so
that our submission timing doesn't perfectly correlate with thousands of
other LLM-driven systems hitting the same headline. Tests verify the
delay is applied (or skipped), bounded, and patchable.

market_status: returns `(is_open, reason)` so callers log WHY a trade
was skipped. Tested against a fake TradingClient.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from trader.execution.broker import AlpacaBroker, BrokerOrder


class _FakeClock:
    """Records the values passed to time.sleep so we can assert."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


class _DeterministicRng:
    """A `random.Random` lookalike whose `uniform` returns a preset list."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def uniform(self, a: float, b: float) -> float:
        del a, b
        return self._values.pop(0)


class _FakeTradingClient:
    """Captures submit_order args and returns a synthetic response."""

    def __init__(
        self, *, is_open: bool = True, next_open: datetime | None = None
    ) -> None:
        self.is_open = is_open
        self.next_open = next_open
        self.submitted: list[object] = []

    def submit_order(self, req: object):
        self.submitted.append(req)
        return SimpleNamespace(id="alpaca-order-id-stub")

    def get_clock(self):
        return SimpleNamespace(
            is_open=self.is_open,
            next_open=self.next_open,
            next_close=self.next_open + timedelta(hours=6) if self.next_open else None,
        )


def _broker_with_fakes(
    *,
    anti_herd_range=(0.0, 5.0),
    sleep=None,
    rng=None,
    client=None,
    monkeypatch,
) -> AlpacaBroker:
    """Build an AlpacaBroker without touching the real Alpaca SDK.

    We patch the import path used in `AlpacaBroker.__init__` so that
    `TradingClient` is replaced before construction.
    """
    fake_client = client or _FakeTradingClient()

    class _StubTradingClient:
        def __new__(cls, *args, **kwargs):
            del args, kwargs
            return fake_client

    monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "s")
    monkeypatch.setattr(
        "alpaca.trading.client.TradingClient",
        _StubTradingClient,
    )
    from trader.config import get_settings

    get_settings.cache_clear()

    broker = AlpacaBroker(
        anti_herd_delay_range_s=anti_herd_range,
        sleep_fn=sleep or _FakeClock(),
        rng=rng,
    )
    get_settings.cache_clear()
    return broker


def test_anti_herd_delay_applied_when_range_positive(monkeypatch):
    clock = _FakeClock()
    rng = _DeterministicRng([2.5])
    broker = _broker_with_fakes(
        anti_herd_range=(0.0, 5.0),
        sleep=clock,
        rng=rng,
        monkeypatch=monkeypatch,
    )
    broker.submit(BrokerOrder(client_order_id="c1", ticker="SPY", side="buy", qty=10))
    assert clock.slept == [2.5]


def test_anti_herd_delay_skipped_when_range_is_zero(monkeypatch):
    """Setting max=0 disables the delay (e.g. for backtests)."""
    clock = _FakeClock()
    broker = _broker_with_fakes(
        anti_herd_range=(0.0, 0.0),
        sleep=clock,
        monkeypatch=monkeypatch,
    )
    broker.submit(BrokerOrder(client_order_id="c2", ticker="SPY", side="buy", qty=10))
    assert clock.slept == []


def test_anti_herd_delay_bounded_within_range(monkeypatch):
    """uniform(0, 5) must return a value in [0, 5]. We verify by
    repeating many real submits and asserting the sleep values are all
    in-range."""
    import random as real_random

    clock = _FakeClock()
    broker = _broker_with_fakes(
        anti_herd_range=(0.0, 5.0),
        sleep=clock,
        rng=real_random.Random(42),
        monkeypatch=monkeypatch,
    )
    for i in range(50):
        broker.submit(
            BrokerOrder(client_order_id=f"c{i}", ticker="SPY", side="buy", qty=1)
        )
    assert all(0.0 <= s <= 5.0 for s in clock.slept)
    # And we did actually sleep 50 times
    assert len(clock.slept) == 50


def test_env_override_changes_max_delay(monkeypatch):
    monkeypatch.setenv("TRADER_ANTI_HERD_DELAY_MAX_S", "1.0")
    clock = _FakeClock()
    rng = _DeterministicRng([0.5])
    broker = _broker_with_fakes(
        anti_herd_range=(0.0, 5.0),  # would be 5s default, env should override
        sleep=clock,
        rng=rng,
        monkeypatch=monkeypatch,
    )
    broker.submit(BrokerOrder(client_order_id="c3", ticker="SPY", side="buy", qty=10))
    # Env says max=1.0; rng was prepped to return 0.5, which is in [0, 1]
    assert clock.slept == [0.5]
    # Internal state should reflect the env-overridden cap
    assert broker._anti_herd_max_s == 1.0


def test_market_status_returns_open_when_clock_is_open(monkeypatch):
    fake = _FakeTradingClient(is_open=True)
    broker = _broker_with_fakes(client=fake, monkeypatch=monkeypatch)
    is_open, reason = broker.market_status()
    assert is_open is True
    assert reason == "open"


def test_market_status_returns_closed_with_next_open(monkeypatch):
    next_open = datetime(2026, 5, 21, 13, 30, tzinfo=UTC)
    fake = _FakeTradingClient(is_open=False, next_open=next_open)
    broker = _broker_with_fakes(client=fake, monkeypatch=monkeypatch)
    is_open, reason = broker.market_status()
    assert is_open is False
    assert "closed" in reason
    assert "2026-05-21" in reason


def test_market_status_handles_client_error(monkeypatch):
    """If get_clock() raises, we should fail closed (market not open)
    rather than crash."""

    class _FailingClient(_FakeTradingClient):
        def get_clock(self):
            raise RuntimeError("alpaca 503")

    broker = _broker_with_fakes(client=_FailingClient(), monkeypatch=monkeypatch)
    is_open, reason = broker.market_status()
    assert is_open is False
    assert "clock_unavailable" in reason


def test_market_is_open_returns_just_bool_for_backcompat(monkeypatch):
    fake = _FakeTradingClient(is_open=True)
    broker = _broker_with_fakes(client=fake, monkeypatch=monkeypatch)
    assert broker.market_is_open() is True
    fake.is_open = False
    assert broker.market_is_open() is False


def test_submit_returns_alpaca_order_id(monkeypatch):
    """Smoke: submit() still returns the alpaca order id string after the
    anti-herd refactor."""
    fake = _FakeTradingClient()
    broker = _broker_with_fakes(
        client=fake,
        anti_herd_range=(0.0, 0.0),  # disable delay for speed
        monkeypatch=monkeypatch,
    )
    order_id = broker.submit(BrokerOrder(client_order_id="c4", ticker="QQQ", side="sell", qty=5))
    assert order_id == "alpaca-order-id-stub"
    assert len(fake.submitted) == 1


def test_invalid_env_value_falls_back_to_default(monkeypatch):
    """A garbage TRADER_ANTI_HERD_DELAY_MAX_S should not crash; default applies."""
    monkeypatch.setenv("TRADER_ANTI_HERD_DELAY_MAX_S", "not-a-number")
    clock = _FakeClock()
    rng = _DeterministicRng([1.0])
    broker = _broker_with_fakes(
        anti_herd_range=(0.0, 5.0),
        sleep=clock,
        rng=rng,
        monkeypatch=monkeypatch,
    )
    broker.submit(BrokerOrder(client_order_id="c5", ticker="SPY", side="buy", qty=1))
    # Default 0-5 range still applied
    assert clock.slept == [1.0]
    assert broker._anti_herd_max_s == 5.0


@pytest.mark.parametrize("seed", [1, 42, 100, 777])
def test_anti_herd_is_actually_random_across_seeds(seed, monkeypatch):
    """With real RNG, two different seeds should produce different delays
    on average — confirming this isn't accidentally deterministic."""
    import random as real_random

    clock = _FakeClock()
    rng = real_random.Random(seed)
    broker = _broker_with_fakes(
        anti_herd_range=(0.0, 5.0),
        sleep=clock,
        rng=rng,
        monkeypatch=monkeypatch,
    )
    for i in range(5):
        broker.submit(BrokerOrder(client_order_id=f"c{seed}_{i}", ticker="SPY", side="buy", qty=1))
    assert len(set(clock.slept)) > 1  # not all the same value
