"""Tests for Store(..., bulk_load=True).

The bulk-load path only relaxes durability PRAGMAs and batches each day's
inserts into a single transaction. It must produce results that are
byte-for-byte identical to the default path, and stay idempotent across
repeated upserts (same conflict key).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from trader.options.models import OptionQuoteBar
from trader.storage.store import Store


def _bars(n, base=datetime(2021, 6, 1, 9, 30)):
    return [
        OptionQuoteBar(
            timestamp=base + timedelta(minutes=i % 390),
            ticker="QQQ",
            expiration=date(2021, 7, 16),
            strike=300 + (i % 40) * 0.5,
            call_put="C" if i % 2 else "P",
            bid=1.2,
            ask=1.3,
            underlying_price=350.0,
            bid_size=10,
            ask_size=12,
            bid_exchange=1,
            ask_exchange=1,
            bid_condition=0,
            ask_condition=0,
            source="theta",
        )
        for i in range(n)
    ]


def test_bulk_load_matches_default(tmp_path: Path):
    bars = _bars(3000)
    a = Store(tmp_path / "a.sqlite", bulk_load=False)
    a.upsert_option_quote_bars_1m("QQQ", bars)
    b = Store(tmp_path / "b.sqlite", bulk_load=True)
    b.upsert_option_quote_bars_1m("QQQ", bars)
    ra = a.get_option_quote_bars_1m("QQQ", trade_date="2021-06-01")
    rb = b.get_option_quote_bars_1m("QQQ", trade_date="2021-06-01")
    assert [vars(x) for x in ra] == [vars(x) for x in rb]


def test_bulk_load_idempotent(tmp_path: Path):
    bars = _bars(3000)
    s = Store(tmp_path / "c.sqlite", bulk_load=True)
    s.upsert_option_quote_bars_1m("QQQ", bars)
    s.upsert_option_quote_bars_1m("QQQ", bars)  # twice
    assert len(s.get_option_quote_bars_1m("QQQ", trade_date="2021-06-01")) == len(
        {(x.timestamp, x.strike, x.call_put) for x in bars}
    )
