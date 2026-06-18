"""SimBroker portfolio accounting tests."""

from __future__ import annotations

import pytest

from trader.execution.broker import SimBroker
from trader.storage.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "trader.sqlite")


def test_initial_state(store):
    b = SimBroker("BrainA", "QQQ", store, starting_cash=10_000, last_price=100)
    assert b.cash() == 10_000
    assert b.position_qty() == 0
    assert b.equity() == 10_000


def test_buy_updates_cash_position_avg(store):
    b = SimBroker("BrainA", "QQQ", store, starting_cash=10_000, last_price=100)
    fill = b.fill_at_market("buy", qty=50, price=100)
    assert fill.filled_qty == 50
    assert b.cash() == 5_000
    assert b.position_qty() == 50
    assert b.avg_cost() == 100


def test_buy_then_buy_recomputes_avg(store):
    b = SimBroker("BrainA", "QQQ", store, starting_cash=10_000, last_price=100)
    b.fill_at_market("buy", qty=50, price=100)
    b.fill_at_market("buy", qty=10, price=110)
    # avg = (50*100 + 10*110) / 60 = 6100 / 60 = 101.6666...
    assert b.position_qty() == 60
    assert b.avg_cost() == pytest.approx(101.6666, abs=1e-3)


def test_sell_realizes_pnl(store):
    b = SimBroker("BrainA", "QQQ", store, starting_cash=10_000, last_price=100)
    b.fill_at_market("buy", qty=50, price=100)  # 50 sh @ 100 → cash=5000
    b.fill_at_market("sell", qty=50, price=120)  # cash=5000+6000=11000
    assert b.cash() == 11_000
    assert b.position_qty() == 0
    assert b.avg_cost() == 0  # reset when flat


def test_oversell_raises(store):
    b = SimBroker("BrainA", "QQQ", store, starting_cash=10_000, last_price=100)
    with pytest.raises(ValueError):
        b.fill_at_market("sell", qty=10, price=100)


def test_insufficient_cash_raises(store):
    b = SimBroker("BrainA", "QQQ", store, starting_cash=100, last_price=100)
    with pytest.raises(ValueError):
        b.fill_at_market("buy", qty=10, price=100)


def test_brains_have_independent_portfolios(store):
    a = SimBroker("BrainA", "QQQ", store, starting_cash=10_000, last_price=100)
    b = SimBroker("BrainB", "QQQ", store, starting_cash=10_000, last_price=100)
    a.fill_at_market("buy", qty=50, price=100)
    assert b.cash() == 10_000
    assert b.position_qty() == 0
