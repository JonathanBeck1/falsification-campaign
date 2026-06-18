"""Memory-safe quote sources for the intraday backtest engine.

The intraday research engine must never load a whole date window into memory: a
single year of ``option_quote_bars_1m`` is ~100M+ rows. These sources expose a
day-at-a-time interface so the engine can stream one trade-date, process it, and
release it before reading the next.

Two backends share one ``QuoteSource`` protocol:

- :class:`SqliteQuoteSource` wraps :class:`~trader.storage.store.Store` and runs
  one bounded query per trade-date.
- :class:`LakeQuoteSource` wraps :class:`~trader.storage.parquet_lake.ParquetLake`
  so DuckDB pushes the ``trade_date`` filter down to the hive partition layout and
  reads only the day's partition.

Both enumerate trade-dates cheaply (SQL aggregate / partition scan) so iterating a
range never materializes more than one day of bars at a time.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from trader.options.models import OptionQuoteBar
    from trader.storage.parquet_lake import ParquetLake
    from trader.storage.store import Store


@runtime_checkable
class QuoteSource(Protocol):
    """A backend that yields one trade-date of option quote bars at a time."""

    def iter_days(
        self, ticker: str, start: date, end: date
    ) -> Iterator[tuple[date, list[OptionQuoteBar]]]:
        """Yield ``(trade_date, bars)`` for each populated day in ``[start, end]``.

        Days are emitted in chronological order. Only days with at least one row
        are yielded (empty calendar days are skipped), mirroring how the engine
        treated absent days. Implementations MUST load one day at a time so the
        caller never holds more than a single trade-date in memory.
        """
        ...

    def get_day(self, ticker: str, trade_date: date) -> list[OptionQuoteBar]:
        """Return all option quote bars for a single ``trade_date``."""
        ...


class SqliteQuoteSource:
    """Day-at-a-time quote source backed by a :class:`Store`."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def get_day(self, ticker: str, trade_date: date) -> list[OptionQuoteBar]:
        return self._store.get_option_quote_bars_1m(ticker, trade_date=trade_date.isoformat())

    def iter_days(
        self, ticker: str, start: date, end: date
    ) -> Iterator[tuple[date, list[OptionQuoteBar]]]:
        for trade_date in self._populated_dates(ticker, start, end):
            bars = self.get_day(ticker, trade_date)
            if bars:
                yield trade_date, bars

    def _populated_dates(self, ticker: str, start: date, end: date) -> list[date]:
        coverage = self._store.intraday_quote_coverage(
            ticker, since=start.isoformat(), until=end.isoformat()
        )
        dates: list[date] = []
        for row in coverage.get("by_date", []):
            trade_date = _coerce_date(row["trade_date"])
            if start <= trade_date <= end:
                dates.append(trade_date)
        return sorted(dates)


class LakeQuoteSource:
    """Day-at-a-time quote source backed by a date-partitioned Parquet lake."""

    def __init__(self, lake_path: str, *, lake: ParquetLake | None = None) -> None:
        if lake is None:
            from trader.storage.parquet_lake import ParquetLake

            lake = ParquetLake(lake_path)
        self._lake = lake

    def get_day(self, ticker: str, trade_date: date) -> list[OptionQuoteBar]:
        return self._lake.get_option_quote_bars_1m(ticker, trade_date=trade_date.isoformat())

    def iter_days(
        self, ticker: str, start: date, end: date
    ) -> Iterator[tuple[date, list[OptionQuoteBar]]]:
        for trade_date in self._populated_dates(ticker, start, end):
            bars = self.get_day(ticker, trade_date)
            if bars:
                yield trade_date, bars

    def _populated_dates(self, ticker: str, start: date, end: date) -> list[date]:
        dates: list[date] = []
        for raw in self._lake.available_dates(ticker):
            trade_date = _coerce_date(raw)
            if start <= trade_date <= end:
                dates.append(trade_date)
        return sorted(dates)


def _coerce_date(value: object) -> date:
    from datetime import datetime

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
