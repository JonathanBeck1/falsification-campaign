from __future__ import annotations

from pathlib import Path

import duckdb

from trader.storage.parquet_lake import ParquetLake


def _write_fixture(base: Path) -> None:
    """A 1-day hive-partitioned lake fixture with bars that should each be kept or
    dropped by get_decision_bars' time / strike-band / DTE filters."""
    rows = [
        # quote_ts, ticker, expiration, strike, call_put, bid, ask, underlying, trade_date
        ("2021-01-04T09:45:00-05:00", "QQQ", "2021-02-08", 300.0, "Put", 1.0, 1.1, 300.0, "2021-01-04"),  # KEEP
        ("2021-01-04T12:00:00-05:00", "QQQ", "2021-02-08", 300.0, "Put", 1.0, 1.1, 300.0, "2021-01-04"),  # drop: time
        ("2021-01-04T09:45:00-05:00", "QQQ", "2021-02-08", 400.0, "Put", 1.0, 1.1, 300.0, "2021-01-04"),  # drop: far strike
        ("2021-01-04T09:45:00-05:00", "QQQ", "2021-01-09", 300.0, "Put", 1.0, 1.1, 300.0, "2021-01-04"),  # drop: 5 DTE
    ]
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t(quote_ts VARCHAR, ticker VARCHAR, expiration VARCHAR, strike DOUBLE, "
        "call_put VARCHAR, bid DOUBLE, ask DOUBLE, underlying_price DOUBLE, bid_size INTEGER, "
        "ask_size INTEGER, bid_exchange INTEGER, ask_exchange INTEGER, bid_condition INTEGER, "
        "ask_condition INTEGER, source VARCHAR, trade_date VARCHAR)"
    )
    for r in rows:
        con.execute(
            "INSERT INTO t VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,'test',?)", r
        )
    out = base / "option_quote_bars_1m"
    con.execute(f"COPY t TO '{out}' (FORMAT PARQUET, PARTITION_BY (trade_date))")
    con.close()


def test_get_decision_bars_filters_time_strike_and_dte(tmp_path: Path):
    _write_fixture(tmp_path)
    lake = ParquetLake(str(tmp_path))
    bars = lake.get_decision_bars(
        "QQQ", since="2021-01-04", until="2021-01-04", times=["09:45:00"], strike_band=0.15, dte_lo=19, dte_hi=47
    )
    assert len(bars) == 1  # only the 09:45 / near-money / 35-DTE bar survives all filters
    bar = bars[0]
    assert bar.strike == 300.0
    assert bar.dte == 35
    assert bar.timestamp.strftime("%H:%M:%S") == "09:45:00"


def test_get_decision_bars_multiple_times(tmp_path: Path):
    _write_fixture(tmp_path)
    lake = ParquetLake(str(tmp_path))
    bars = lake.get_decision_bars(
        "QQQ", since="2021-01-04", until="2021-01-04", times=["09:45:00", "12:00:00"], strike_band=0.15, dte_lo=19, dte_hi=47
    )
    # both 09:45 and 12:00 near-money/35-DTE bars now qualify on time
    assert {b.timestamp.strftime("%H:%M:%S") for b in bars} == {"09:45:00", "12:00:00"}


def test_get_decision_bars_empty_times_returns_nothing(tmp_path: Path):
    _write_fixture(tmp_path)
    lake = ParquetLake(str(tmp_path))
    assert lake.get_decision_bars("QQQ", since="2021-01-04", until="2021-01-04", times=[]) == []
