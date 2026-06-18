from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from trader.options.models import OptionQuoteBar
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


def test_ledger_upsert_is_idempotent_and_updates(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    store.upsert_backfill_ledger("spy", "2024-06-03", status="failed", attempts=1, last_error="boom")
    store.upsert_backfill_ledger("SPY", "2024-06-03", status="done", expirations_pulled=2, quote_rows=120, attempts=3)

    ledger = store.get_backfill_ledger("SPY")
    assert len(ledger) == 1
    row = ledger[0]
    assert row["status"] == "done"
    assert row["quote_rows"] == 120
    assert row["expirations_pulled"] == 2
    assert row["last_error"] is None


def test_get_backfill_done_dates_excludes_failed(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    store.upsert_backfill_ledger("SPY", "2024-06-03", status="done", quote_rows=10)
    store.upsert_backfill_ledger("SPY", "2024-06-04", status="empty")
    store.upsert_backfill_ledger("SPY", "2024-06-05", status="failed", last_error="boom")

    done = store.get_backfill_done_dates("SPY")
    assert done == {"2024-06-03", "2024-06-04"}


def test_ledger_bounded_query(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    for day in ("2024-06-03", "2024-06-04", "2024-06-05"):
        store.upsert_backfill_ledger("SPY", day, status="done")
    rows = store.get_backfill_ledger("SPY", since="2024-06-04", until="2024-06-05")
    assert [row["trade_date"] for row in rows] == ["2024-06-04", "2024-06-05"]


def test_intraday_quote_coverage_aggregates(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    store.upsert_option_quote_bars_1m(
        "SPY",
        [
            _bar(date(2024, 6, 3), 519, "Put", spot=586.0),
            _bar(date(2024, 6, 3), 520, "Call", spot=586.0),
            _bar(date(2024, 6, 4), 519, "Put", spot=None),  # missing spot
        ],
    )
    coverage = store.intraday_quote_coverage("SPY")
    by_date = {row["trade_date"]: row for row in coverage["by_date"]}
    assert by_date["2024-06-03"]["rows"] == 2
    assert by_date["2024-06-03"]["expirations"] == 1
    assert by_date["2024-06-04"]["rows"] == 1
    assert coverage["rows_missing_spot"] == 1
