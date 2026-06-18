"""Round-trip tests for the Parquet lake export/read path.

Seed a Store with two trade_dates, export it to a date-partitioned Parquet
lake, then assert ParquetLake reads back exactly what Store.get_option_quote_bars_1m
returns. Also exercise the since/until/trade_date filters and available_dates().

Skipped cleanly when duckdb is not installed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from trader.options.models import OptionQuoteBar
from trader.storage.parquet_export import export_lake
from trader.storage.parquet_lake import ParquetLake
from trader.storage.store import Store


def _bars(n, base):
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


def _seed_store(db_path: Path) -> Store:
    store = Store(db_path)
    store.upsert_option_quote_bars_1m("QQQ", _bars(500, datetime(2021, 6, 1, 9, 30)))
    store.upsert_option_quote_bars_1m("QQQ", _bars(500, datetime(2021, 6, 2, 9, 30)))
    return store


def test_lake_roundtrip_matches_store(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"
    store = _seed_store(db_path)
    out = tmp_path / "lake"

    manifest = export_lake(db_path=db_path, out_dir=out, ticker="QQQ", since=None, until=None)
    assert manifest["days"] == 2
    assert manifest["rows"] > 0

    lake = ParquetLake(str(out))
    for d in ("2021-06-01", "2021-06-02"):
        expected = store.get_option_quote_bars_1m("QQQ", trade_date=d)
        actual = lake.get_option_quote_bars_1m("QQQ", trade_date=d)
        assert actual == expected


def test_lake_since_until_and_available_dates(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"
    store = _seed_store(db_path)
    out = tmp_path / "lake"
    export_lake(db_path=db_path, out_dir=out, ticker="QQQ", since=None, until=None)
    lake = ParquetLake(str(out))

    assert lake.available_dates("QQQ") == ["2021-06-01", "2021-06-02"]
    assert lake.available_dates() == ["2021-06-01", "2021-06-02"]

    only_first = lake.get_option_quote_bars_1m("QQQ", until="2021-06-01")
    assert only_first == store.get_option_quote_bars_1m("QQQ", until="2021-06-01")
    assert {b.timestamp.date() for b in only_first} == {date(2021, 6, 1)}

    only_second = lake.get_option_quote_bars_1m("QQQ", since="2021-06-02")
    assert only_second == store.get_option_quote_bars_1m("QQQ", since="2021-06-02")
    assert {b.timestamp.date() for b in only_second} == {date(2021, 6, 2)}

    both = lake.get_option_quote_bars_1m("QQQ", since="2021-06-01", until="2021-06-02")
    assert both == store.get_option_quote_bars_1m("QQQ", since="2021-06-01", until="2021-06-02")


def test_export_partition_filter(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"
    _seed_store(db_path)
    out = tmp_path / "lake"

    manifest = export_lake(db_path=db_path, out_dir=out, ticker="QQQ", since="2021-06-02", until=None)
    assert manifest["days"] == 1

    lake = ParquetLake(str(out))
    assert lake.available_dates("QQQ") == ["2021-06-02"]
