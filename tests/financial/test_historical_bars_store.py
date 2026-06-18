from __future__ import annotations

import sqlite3
from pathlib import Path

from trader.storage.migrations import latest_version
from trader.storage.store import Store


def _bar(
    trade_date: str,
    *,
    open: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: float = 1_000.0,
    vix_close: float | None = None,
    yield_curve_10y_2y: float | None = None,
) -> dict[str, float | str | None]:
    return {
        "trade_date": trade_date,
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "vix_close": vix_close,
        "yield_curve_10y_2y": yield_curve_10y_2y,
    }


def test_writes_rows_and_reads_sorted_by_trade_date(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")

    written = store.upsert_historical_bars(
        "QQQ",
        [
            _bar("2026-01-03", close=103.0),
            _bar("2026-01-01", close=101.0),
            _bar("2026-01-02", close=102.0),
        ],
    )

    rows = store.get_historical_bars("QQQ")
    assert written == 3
    assert [row["trade_date"] for row in rows] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert [row["close"] for row in rows] == [101.0, 102.0, 103.0]


def test_reupsert_overwrites_ohlcv_and_preserves_macro_values_when_new_values_are_none(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.upsert_historical_bars(
        "QQQ",
        [
            _bar(
                "2026-01-02",
                open=100.0,
                high=111.0,
                low=99.0,
                close=105.0,
                volume=1_000.0,
                vix_close=17.5,
                yield_curve_10y_2y=0.42,
            )
        ],
    )

    written = store.upsert_historical_bars(
        "QQQ",
        [
            _bar(
                "2026-01-02",
                open=101.0,
                high=112.0,
                low=100.0,
                close=106.0,
                volume=2_000.0,
                vix_close=None,
                yield_curve_10y_2y=None,
            )
        ],
    )

    row = store.get_historical_bars("QQQ")[0]
    assert written == 1
    assert row["open"] == 101.0
    assert row["high"] == 112.0
    assert row["low"] == 100.0
    assert row["close"] == 106.0
    assert row["volume"] == 2_000.0
    assert row["vix_close"] == 17.5
    assert row["yield_curve_10y_2y"] == 0.42


def test_since_until_filters_are_inclusive(tmp_path: Path):
    store = Store(tmp_path / "trader.sqlite")
    store.upsert_historical_bars(
        "QQQ",
        [
            _bar("2026-01-01"),
            _bar("2026-01-02"),
            _bar("2026-01-03"),
            _bar("2026-01-04"),
        ],
    )

    rows = store.get_historical_bars("QQQ", since="2026-01-02", until="2026-01-03")

    assert [row["trade_date"] for row in rows] == ["2026-01-02", "2026-01-03"]


def test_historical_bars_table_exists_after_latest_migration(tmp_path: Path):
    db_path = tmp_path / "trader.sqlite"

    Store(db_path)

    assert latest_version() == 8
    with sqlite3.connect(db_path) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'historical_bars'"
        ).fetchone()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(historical_bars)").fetchall()}
    assert table is not None
    assert {"ticker", "trade_date", "open", "high", "low", "close", "volume"}.issubset(columns)
