from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from trader.options.models import OptionQuoteBar
from trader.options.quality import (
    format_intraday_quote_coverage_report,
    summarize_intraday_quote_coverage,
)
from trader.storage.store import Store


def _bar(trade_day: date, strike: float, side: str, *, spot: float | None) -> OptionQuoteBar:
    return OptionQuoteBar(
        timestamp=datetime(trade_day.year, trade_day.month, trade_day.day, 10, 0),
        ticker="SPY",
        expiration=date(2024, 7, 19),
        strike=strike,
        call_put=side,
        bid=1.0,
        ask=1.1,
        underlying_price=spot,
    )


def _seed(store: Store) -> None:
    # Cover 2024-06-03 and 2024-06-05 but NOT 2024-06-04 (a real trading day -> a gap).
    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _bar(date(2024, 6, 3), 519, "Put", spot=586.0),
            _bar(date(2024, 6, 3), 520, "Call", spot=586.0),
            _bar(date(2024, 6, 5), 519, "Put", spot=None),  # missing spot
        ],
    )


def test_coverage_detects_missing_trading_day_and_missing_spot(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    _seed(store)
    coverage = summarize_intraday_quote_coverage(
        store, ticker="SPY", since="2024-06-03", until="2024-06-05", min_rows_per_day_warning=1
    )
    assert coverage.covered_days == 2
    assert coverage.expected_trading_days == 3  # Mon/Tue/Wed
    assert coverage.missing_days == ("2024-06-04",)
    assert coverage.rows_missing_spot == 1
    assert "missing_trading_days" in coverage.warnings
    assert "rows_missing_underlying_price" in coverage.warnings


def test_coverage_flags_low_row_days(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    _seed(store)
    coverage = summarize_intraday_quote_coverage(
        store, ticker="SPY", since="2024-06-03", until="2024-06-05", min_rows_per_day_warning=5_000
    )
    assert "low_coverage_days" in coverage.warnings


def test_coverage_report_renders(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    _seed(store)
    coverage = summarize_intraday_quote_coverage(store, ticker="SPY", since="2024-06-03", until="2024-06-05")
    report = format_intraday_quote_coverage_report(coverage)
    assert "# SPY Intraday Quote Coverage" in report
    assert "covered_days: 2" in report
    assert "missing_days: 1" in report
    assert "2024-06-04" in report


def test_coverage_empty_store(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    coverage = summarize_intraday_quote_coverage(store, ticker="SPY")
    assert coverage.covered_days == 0
    assert coverage.option_rows == 0
    assert "no_intraday_rows" in coverage.warnings
