"""Phase 1 keystone tests: memory-safe, lake-backed quote sources.

Validates that:
1. ``SqliteQuoteSource`` and ``LakeQuoteSource`` yield identical days.
2. The intraday engine produces identical backtest results from a raw list, the
   SQLite source, and the lake source on a small multi-day fixture.
3. The engine streams day-by-day -- it never holds more than one trade-date of
   quote bars in memory (proven with weakref + gc on an instrumented source).

All assertions use tiny synthetic fixtures; nothing reads the live dataset.
"""

from __future__ import annotations

import gc
import weakref
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trader.options.intraday import (
    IntradayIronCondorBacktestConfig,
    IntradayIronCondorSelectorConfig,
    run_intraday_iron_condor_backtest,
)
from trader.options.models import OptionQuoteBar
from trader.options.sources import LakeQuoteSource, QuoteSource, SqliteQuoteSource
from trader.storage.store import Store

EASTERN = ZoneInfo("America/New_York")
EXPIRATION = date(2026, 6, 26)
TRADE_DATES = (date(2026, 5, 22), date(2026, 5, 26), date(2026, 5, 27))


def _bar(
    timestamp: datetime,
    strike: float,
    call_put: str,
    bid: float,
    ask: float,
) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=timestamp,
        ticker="SPY",
        expiration=EXPIRATION,
        strike=strike,
        call_put=call_put,
        bid=bid,
        ask=ask,
        underlying_price=585.0,
        bid_size=10,
        ask_size=10,
        bid_exchange=22,
        ask_exchange=73,
        bid_condition=50,
        ask_condition=50,
        source="unit-test",
    )


def _day_bars(trade_date: date) -> list[OptionQuoteBar]:
    """A tradeable condor: opens at 09:45, hits profit target at 10:15."""
    entry_ts = datetime(trade_date.year, trade_date.month, trade_date.day, 9, 45, tzinfo=EASTERN)
    exit_ts = datetime(trade_date.year, trade_date.month, trade_date.day, 10, 15, tzinfo=EASTERN)
    return [
        _bar(entry_ts, 555, "Put", 0.50, 0.55),
        _bar(entry_ts, 560, "Put", 1.20, 1.30),
        _bar(entry_ts, 610, "Call", 1.20, 1.30),
        _bar(entry_ts, 615, "Call", 0.50, 0.55),
        _bar(exit_ts, 555, "Put", 0.35, 0.40),
        _bar(exit_ts, 560, "Put", 0.60, 0.65),
        _bar(exit_ts, 610, "Call", 0.60, 0.65),
        _bar(exit_ts, 615, "Call", 0.35, 0.40),
    ]


def _all_bars() -> list[OptionQuoteBar]:
    bars: list[OptionQuoteBar] = []
    for trade_date in TRADE_DATES:
        bars.extend(_day_bars(trade_date))
    return bars


def _config() -> IntradayIronCondorBacktestConfig:
    return IntradayIronCondorBacktestConfig(
        ticker="SPY",
        start=TRADE_DATES[0],
        end=TRADE_DATES[-1],
        selector=IntradayIronCondorSelectorConfig(
            min_dte=30,
            max_dte=45,
            wing_width=5.0,
            target_short_bid=1.20,
            min_credit=0.05,
        ),
        entry_time="09:45:00",
        profit_target_pct=0.50,
        stop_loss_credit_multiple=2.0,
    )


def _seed_store(db_path: Path) -> Store:
    store = Store(db_path)
    for trade_date in TRADE_DATES:
        store.upsert_option_quote_bars_1m("SPY", _day_bars(trade_date))
    return store


def _trade_projection(result) -> list[tuple]:
    """Compare trades without the random per-run trade_id/run_id."""
    return [
        (
            t.entry_ts,
            t.exit_ts,
            t.expiration,
            t.short_put_strike,
            t.long_put_strike,
            t.short_call_strike,
            t.long_call_strike,
            t.entry_credit,
            t.exit_debit,
            t.pnl,
            t.exit_reason,
        )
        for t in result.trades
    ]


def test_sqlite_source_is_a_quote_source(tmp_path: Path):
    store = _seed_store(tmp_path / "trader.sqlite")
    source = SqliteQuoteSource(store)
    assert isinstance(source, QuoteSource)


def test_sqlite_source_streams_one_day_per_iteration(tmp_path: Path):
    store = _seed_store(tmp_path / "trader.sqlite")
    source = SqliteQuoteSource(store)

    days = list(source.iter_days("SPY", TRADE_DATES[0], TRADE_DATES[-1]))

    assert [d for d, _ in days] == list(TRADE_DATES)
    for trade_date, bars in days:
        assert {b.trade_date for b in bars} == {trade_date}
        assert bars == source.get_day("SPY", trade_date)


def test_sqlite_source_respects_window_bounds(tmp_path: Path):
    store = _seed_store(tmp_path / "trader.sqlite")
    source = SqliteQuoteSource(store)

    days = list(source.iter_days("SPY", TRADE_DATES[1], TRADE_DATES[1]))

    assert [d for d, _ in days] == [TRADE_DATES[1]]


def test_engine_result_matches_between_list_and_sqlite_source(tmp_path: Path):
    store = _seed_store(tmp_path / "trader.sqlite")
    source = SqliteQuoteSource(store)
    config = _config()

    list_result = run_intraday_iron_condor_backtest(_all_bars(), config)
    sqlite_result = run_intraday_iron_condor_backtest(source, config)

    assert list_result.summary.trade_count == len(TRADE_DATES)
    assert sqlite_result.summary == list_result.summary
    assert _trade_projection(sqlite_result) == _trade_projection(list_result)


# --- Lake-backed parity (DuckDB) -------------------------------------------


def test_lake_and_sqlite_sources_yield_identical_days(tmp_path: Path):
    pytest.importorskip("duckdb")
    from trader.storage.parquet_export import export_lake

    db_path = tmp_path / "trader.sqlite"
    store = _seed_store(db_path)
    out = tmp_path / "lake"
    export_lake(db_path=db_path, out_dir=out, ticker="SPY", since=None, until=None)

    sqlite_source = SqliteQuoteSource(store)
    lake_source = LakeQuoteSource(str(out))

    sqlite_days = list(sqlite_source.iter_days("SPY", TRADE_DATES[0], TRADE_DATES[-1]))
    lake_days = list(lake_source.iter_days("SPY", TRADE_DATES[0], TRADE_DATES[-1]))

    assert [d for d, _ in sqlite_days] == [d for d, _ in lake_days] == list(TRADE_DATES)
    for (s_date, s_bars), (l_date, l_bars) in zip(sqlite_days, lake_days, strict=True):
        assert s_date == l_date
        assert s_bars == l_bars


def test_engine_result_matches_between_sources(tmp_path: Path):
    pytest.importorskip("duckdb")
    from trader.storage.parquet_export import export_lake

    db_path = tmp_path / "trader.sqlite"
    store = _seed_store(db_path)
    out = tmp_path / "lake"
    export_lake(db_path=db_path, out_dir=out, ticker="SPY", since=None, until=None)

    config = _config()
    list_result = run_intraday_iron_condor_backtest(_all_bars(), config)
    sqlite_result = run_intraday_iron_condor_backtest(SqliteQuoteSource(store), config)
    lake_result = run_intraday_iron_condor_backtest(LakeQuoteSource(str(out)), config)

    assert sqlite_result.summary == list_result.summary == lake_result.summary
    assert (
        _trade_projection(sqlite_result)
        == _trade_projection(list_result)
        == _trade_projection(lake_result)
    )


# --- Memory-safety: the engine holds at most one trade-date in memory --------


class _WeakableBars(list):
    """A list subclass so we can take weakrefs to each day's bar container."""


class _InstrumentedDaySource:
    """In-memory QuoteSource that proves the consumer never accumulates days.

    Before yielding each day it gc-collects and counts how many *previously
    yielded* day containers are still alive. If the engine streamed correctly,
    earlier days are released as soon as the next one is read, so the peak count
    of live prior days stays at or below one. If the engine materialized the
    whole window, the peak would grow to N-1.
    """

    def __init__(self, days: list[tuple[date, list[OptionQuoteBar]]]) -> None:
        self._days = days
        self.max_live_prior = 0
        self.yielded: list[date] = []

    def get_day(self, ticker: str, trade_date: date) -> list[OptionQuoteBar]:
        for trade_date_key, bars in self._days:
            if trade_date_key == trade_date:
                return _WeakableBars(bars)
        return _WeakableBars()

    def iter_days(self, ticker: str, start: date, end: date):
        refs: list[weakref.ref] = []
        for trade_date, bars in self._days:
            if not (start <= trade_date <= end):
                continue
            container = _WeakableBars(bars)
            gc.collect()
            live_prior = sum(1 for ref in refs if ref() is not None)
            self.max_live_prior = max(self.max_live_prior, live_prior)
            refs.append(weakref.ref(container))
            self.yielded.append(trade_date)
            yield trade_date, container


def test_engine_never_holds_more_than_one_day_in_memory():
    days = [(trade_date, _day_bars(trade_date)) for trade_date in TRADE_DATES]
    source = _InstrumentedDaySource(days)
    config = _config()

    result = run_intraday_iron_condor_backtest(source, config)

    assert source.yielded == list(TRADE_DATES)
    assert source.max_live_prior <= 1
    assert result.summary.trade_count == len(TRADE_DATES)


def test_streaming_requires_bounded_window():
    source = _InstrumentedDaySource([(TRADE_DATES[0], _day_bars(TRADE_DATES[0]))])
    config = replace(_config(), start=None, end=None)

    with pytest.raises(ValueError, match=r"requires config\.start and config\.end"):
        run_intraday_iron_condor_backtest(source, config)
