from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from trader.options.backfill import (
    BackfillPermissionError,
    RateLimiter,
    RetryPolicy,
    call_with_retry,
    run_thetadata_quote_backfill,
)
from trader.options.models import OptionContract, OptionQuoteBar
from trader.storage.store import Store

_NO_TIMEOUT = dict(request_pace_s=0.0, request_timeout_s=0.0, sleep_fn=lambda _s: None, log=lambda _m: None)


class _NoDataFound(Exception):
    pass


class FakeClient:
    """In-memory ThetaData stand-in; configurable per-day quote behavior."""

    def __init__(self, *, exp_offset_days: int = 30, quote_error=None, nodata: bool = False) -> None:
        self.exp_offset_days = exp_offset_days
        self.quote_error = quote_error
        self.nodata = nodata
        self.contracts_calls = 0
        self.quote_calls = 0

    def fetch_contracts(self, ticker, *, trade_date, max_dte):
        self.contracts_calls += 1
        expiration = trade_date + timedelta(days=self.exp_offset_days)
        return [
            OptionContract(ticker="SPY", expiration=expiration, strike=strike, call_put=side)
            for strike in (519.0, 520.0, 521.0)
            for side in ("Call", "Put")
        ]

    def fetch_quote_history(self, ticker, *, trade_date, expiration, start_time, end_time, interval, strike_range):
        self.quote_calls += 1
        if self.quote_error is not None:
            raise self.quote_error()
        if self.nodata:
            raise _NoDataFound("No data found for request")
        ts = datetime(trade_date.year, trade_date.month, trade_date.day, 10, 0)
        rows = []
        for strike in (519.0, 520.0, 521.0):
            rows.append(OptionQuoteBar(ts, "SPY", expiration, strike, "Put", 1.0, 1.1))
            rows.append(OptionQuoteBar(ts, "SPY", expiration, strike, "Call", 2.0, 2.1))
        return rows

    def fetch_underlying_quote_history(self, *args, **kwargs):
        return []


# --- RateLimiter ---


def test_rate_limiter_waits_for_min_interval():
    slept: list[float] = []
    clock = [100.0]
    rl = RateLimiter(2.0, sleep_fn=slept.append, monotonic=lambda: clock[0])
    rl.acquire()  # first call: no wait
    clock[0] = 100.5  # 0.5s elapsed
    rl.acquire()  # must wait the remaining 1.5s
    assert slept == pytest.approx([1.5])


def test_rate_limiter_zero_interval_never_sleeps():
    slept: list[float] = []
    rl = RateLimiter(0.0, sleep_fn=slept.append, monotonic=lambda: 0.0)
    rl.acquire()
    rl.acquire()
    assert slept == []


# --- call_with_retry ---


def test_retry_then_succeeds_with_exponential_backoff():
    calls = [0]
    slept: list[float] = []

    def fn():
        calls[0] += 1
        if calls[0] < 3:
            raise RuntimeError("transient boom")
        return "ok"

    out = call_with_retry(
        fn, policy=RetryPolicy(max_retries=4, backoff_base_s=1.0, timeout_s=0.0), sleep_fn=slept.append
    )
    assert out == "ok"
    assert calls[0] == 3
    assert slept == pytest.approx([1.0, 2.0])  # base*2^0, base*2^1


def test_retry_gives_up_after_max_retries():
    def fn():
        raise RuntimeError("always boom")

    with pytest.raises(RuntimeError):
        call_with_retry(fn, policy=RetryPolicy(max_retries=2, timeout_s=0.0), sleep_fn=lambda _s: None)


def test_permission_denied_is_fatal_and_not_retried():
    calls = [0]

    def fn():
        calls[0] += 1
        raise Exception("status=PERMISSION_DENIED requires a STANDARD subscription")

    with pytest.raises(BackfillPermissionError):
        call_with_retry(fn, policy=RetryPolicy(max_retries=5, timeout_s=0.0), sleep_fn=lambda _s: None)
    assert calls[0] == 1


def test_nodata_is_reraised_without_retry():
    calls = [0]

    def fn():
        calls[0] += 1
        raise _NoDataFound("No data found")

    with pytest.raises(_NoDataFound):
        call_with_retry(fn, policy=RetryPolicy(max_retries=5, timeout_s=0.0), sleep_fn=lambda _s: None)
    assert calls[0] == 1


# --- run_thetadata_quote_backfill ---


def test_backfill_happy_path_persists_rows_and_ledger(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    client = FakeClient()
    summary = run_thetadata_quote_backfill(
        client, store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 7), **_NO_TIMEOUT
    )
    assert summary.trading_days == 5
    assert summary.days_done == 5
    assert summary.quote_rows == 30  # 5 days * 1 expiration * 6 rows
    assert store.get_backfill_done_dates("SPY") == {
        "2024-06-03",
        "2024-06-04",
        "2024-06-05",
        "2024-06-06",
        "2024-06-07",
    }
    # parity spot attached to every persisted bar
    bars = store.get_option_quote_bars_1m("SPY")
    assert bars and all(bar.underlying_price is not None for bar in bars)


def test_backfill_skips_market_holiday(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    client = FakeClient()
    # 2024-07-01..05: Jul 4 (Thu) is a market holiday -> 4 sessions, not 5.
    summary = run_thetadata_quote_backfill(
        client, store, ticker="SPY", start=date(2024, 7, 1), end=date(2024, 7, 5), **_NO_TIMEOUT
    )
    assert summary.trading_days == 4
    assert client.contracts_calls == 4


def test_backfill_resume_skips_completed_days(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    run_thetadata_quote_backfill(
        FakeClient(), store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 7), **_NO_TIMEOUT
    )
    second = FakeClient()
    summary = run_thetadata_quote_backfill(
        second, store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 7), **_NO_TIMEOUT
    )
    assert summary.days_attempted == 0
    assert summary.days_skipped == 5
    assert second.contracts_calls == 0


def test_backfill_force_repulls_everything(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    run_thetadata_quote_backfill(
        FakeClient(), store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 5), **_NO_TIMEOUT
    )
    summary = run_thetadata_quote_backfill(
        FakeClient(), store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 5), force=True, **_NO_TIMEOUT
    )
    assert summary.days_attempted == 3
    assert summary.days_skipped == 0


def test_backfill_marks_empty_when_no_quotes(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    summary = run_thetadata_quote_backfill(
        FakeClient(nodata=True), store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 4), **_NO_TIMEOUT
    )
    assert summary.days_empty == 2
    assert summary.days_done == 0
    assert summary.quote_rows == 0
    # empty days are complete -> skipped on resume
    assert store.get_backfill_done_dates("SPY") == {"2024-06-03", "2024-06-04"}


def test_backfill_marks_failed_and_resume_retries(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    client = FakeClient(quote_error=lambda: RuntimeError("transient network boom"))
    summary = run_thetadata_quote_backfill(
        client, store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 4), max_retries=1, **_NO_TIMEOUT
    )
    assert summary.days_failed == 2
    assert summary.days_done == 0
    # failed days are NOT considered complete, so a resume run retries them
    assert store.get_backfill_done_dates("SPY") == set()
    ledger = store.get_backfill_ledger("SPY")
    assert all(row["status"] == "failed" and row["last_error"] for row in ledger)


def test_backfill_permission_denied_aborts_run(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    client = FakeClient(quote_error=lambda: Exception("rpc terminated PERMISSION_DENIED needs STANDARD subscription"))
    with pytest.raises(BackfillPermissionError):
        run_thetadata_quote_backfill(
            client, store, ticker="SPY", start=date(2024, 6, 3), end=date(2024, 6, 5), **_NO_TIMEOUT
        )
    # the day it died on is recorded as failed; the run did not silently continue
    ledger = store.get_backfill_ledger("SPY")
    assert len(ledger) == 1
    assert ledger[0]["status"] == "failed"
