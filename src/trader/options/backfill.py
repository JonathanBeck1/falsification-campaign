"""Resilient, rate-limited, resumable ThetaData option-quote backfill.

ThetaData Value allows ~30 requests/minute on a single server thread, so this
orchestrator paces requests, retries transient failures with backoff, skips
non-trading days, and records per-day progress in a ledger so a multi-day pull
can resume after interruption. It reuses the existing adapter, parity/spot
enrichment, and idempotent quote upsert — it only adds the durability layer.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from trader.options.calendar import trading_days
from trader.options.underlying import (
    attach_put_call_parity_underlying_prices,
    attach_underlying_quote_prices,
)

# Substrings that classify ThetaData/gRPC errors without importing vendor types.
_PERMISSION_MARKERS = ("PERMISSION_DENIED", "STANDARD subscription", "requires a STANDARD")
_NODATA_MARKERS = ("NoDataFound", "No data found")


class BackfillPermissionError(RuntimeError):
    """Raised when ThetaData denies a request due to subscription tier (fatal)."""


def _looks_like_nodata(exc: BaseException) -> bool:
    return any(marker in repr(exc) for marker in _NODATA_MARKERS)


def _looks_like_permission(exc: BaseException) -> bool:
    return any(marker in repr(exc) for marker in _PERMISSION_MARKERS)


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 4
    backoff_base_s: float = 1.0
    timeout_s: float = 30.0


@dataclass(frozen=True)
class BackfillSummary:
    ticker: str
    start: date
    end: date
    trading_days: int
    days_attempted: int
    days_done: int
    days_empty: int
    days_failed: int
    days_skipped: int
    expirations_pulled: int
    quote_rows: int
    requests: int
    elapsed_s: float


class RateLimiter:
    """Enforce a minimum interval between successive `acquire()` calls."""

    def __init__(
        self,
        min_interval_s: float,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_s = max(0.0, min_interval_s)
        self._sleep = sleep_fn
        self._monotonic = monotonic
        self._last: float | None = None

    def acquire(self) -> None:
        if self.min_interval_s <= 0:
            return
        if self._last is not None:
            wait = self.min_interval_s - (self._monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._monotonic()


def _raise_timeout(signum, frame):  # pragma: no cover - signal handler
    raise TimeoutError("ThetaData request exceeded timeout")


def _with_timeout(fn: Callable[[], object], timeout_s: float) -> object:
    """Run `fn` under a real-time alarm. Falls back to no-timeout off the main thread."""
    if timeout_s <= 0 or not hasattr(signal, "SIGALRM"):
        return fn()
    try:
        old = signal.signal(signal.SIGALRM, _raise_timeout)
    except ValueError:
        return fn()  # not the main thread; cannot use signals
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def call_with_retry(
    fn: Callable[[], object],
    *,
    policy: RetryPolicy,
    rate_limiter: RateLimiter | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] | None = None,
    label: str = "",
) -> object:
    """Call `fn` with pacing, per-call timeout, and exponential backoff.

    - Each attempt (including retries) is paced through `rate_limiter`.
    - `PERMISSION_DENIED` is fatal -> `BackfillPermissionError` (no retry).
    - `NoDataFound` is deterministic -> re-raised immediately (caller treats as empty).
    - Other errors (incl. timeouts) retry up to `policy.max_retries`.
    """
    attempt = 0
    while True:
        if rate_limiter is not None:
            rate_limiter.acquire()
        try:
            return _with_timeout(fn, policy.timeout_s)
        except Exception as exc:
            if _looks_like_permission(exc):
                raise BackfillPermissionError(repr(exc)) from exc
            if _looks_like_nodata(exc):
                raise
            attempt += 1
            if attempt > policy.max_retries:
                raise
            if log is not None:
                log(f"retry {label} attempt={attempt}/{policy.max_retries} err={repr(exc)[:140]}")
            sleep_fn(policy.backoff_base_s * (2 ** (attempt - 1)))


def _expirations_in_window(contracts, *, trade_date: date, min_dte: int, max_dte: int) -> list[date]:
    expirations = {
        contract.expiration for contract in contracts if min_dte <= contract.dte_on(trade_date) <= max_dte
    }
    return sorted(expirations)


@dataclass
class _DayResult:
    status: str
    expirations_pulled: int
    quote_rows: int
    requests: int
    last_error: str | None


def _backfill_one_day(
    client,
    store,
    *,
    ticker: str,
    trade_date: date,
    min_dte: int,
    max_dte: int,
    strike_range: int,
    start_time: str,
    end_time: str,
    interval: str,
    underlying_source: str,
    risk_free_rate: float,
    dividend_yield: float,
    policy: RetryPolicy,
    rate_limiter: RateLimiter,
    sleep_fn: Callable[[float], None],
    log: Callable[[str], None] | None,
) -> _DayResult:
    requests = 0

    def _call(fn, label):
        nonlocal requests
        requests += 1
        return call_with_retry(fn, policy=policy, rate_limiter=rate_limiter, sleep_fn=sleep_fn, log=log, label=label)

    contracts = _call(
        lambda: client.fetch_contracts(ticker, trade_date=trade_date, max_dte=max_dte),
        f"contracts {trade_date}",
    )
    expirations = _expirations_in_window(contracts, trade_date=trade_date, min_dte=min_dte, max_dte=max_dte)
    if not expirations:
        return _DayResult("empty", 0, 0, requests, None)

    underlying_quotes = []
    if underlying_source == "stock":
        underlying_quotes = _call(
            lambda: client.fetch_underlying_quote_history(
                ticker, trade_date=trade_date, start_time=start_time, end_time=end_time, interval=interval
            ),
            f"underlying {trade_date}",
        )

    pulled = 0
    total_rows = 0
    last_error: str | None = None
    for expiration in expirations:
        try:
            quotes = _call(
                lambda expiration=expiration: client.fetch_quote_history(
                    ticker,
                    trade_date=trade_date,
                    expiration=expiration,
                    start_time=start_time,
                    end_time=end_time,
                    interval=interval,
                    strike_range=strike_range,
                ),
                f"quotes {trade_date}/{expiration}",
            )
        except BackfillPermissionError:
            raise
        except Exception as exc:
            if _looks_like_nodata(exc):
                continue
            last_error = repr(exc)[:200]
            continue
        if not quotes:
            continue
        if underlying_source == "stock":
            quotes = attach_underlying_quote_prices(quotes, underlying_quotes)
        elif underlying_source == "parity":
            quotes = attach_put_call_parity_underlying_prices(
                quotes, risk_free_rate=risk_free_rate, dividend_yield=dividend_yield
            )
        total_rows += store.upsert_option_quote_bars_1m(ticker, quotes)
        pulled += 1

    if last_error is not None and pulled == 0:
        return _DayResult("failed", pulled, total_rows, requests, last_error)
    status = "done" if total_rows > 0 else "empty"
    return _DayResult(status, pulled, total_rows, requests, last_error)


def run_thetadata_quote_backfill(
    client,
    store,
    *,
    ticker: str = "SPY",
    start: date,
    end: date,
    min_dte: int = 18,
    max_dte: int = 48,
    strike_range: int = 60,
    start_time: str = "09:30:00",
    end_time: str = "16:00:00",
    interval: str = "1m",
    underlying_source: str = "parity",
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
    resume: bool = True,
    force: bool = False,
    request_pace_s: float = 2.1,
    max_retries: int = 4,
    request_timeout_s: float = 30.0,
    backoff_base_s: float = 1.0,
    rate_limiter: RateLimiter | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> BackfillSummary:
    """Pull 1-minute option NBBO quotes for every trading day in [start, end].

    Resumable via the backfill ledger; rate-limited and retry-wrapped for the
    ThetaData Value tier. Returns a summary; raises BackfillPermissionError if
    ThetaData reports the request needs a higher subscription tier.
    """
    symbol = ticker.strip().upper()
    policy = RetryPolicy(max_retries=max_retries, backoff_base_s=backoff_base_s, timeout_s=request_timeout_s)
    if rate_limiter is None:
        rate_limiter = RateLimiter(request_pace_s, sleep_fn=sleep_fn, monotonic=monotonic)

    all_days = trading_days(start, end)
    done = set() if (force or not resume) else store.get_backfill_done_dates(symbol)
    work = [day for day in all_days if day.isoformat() not in done]
    skipped = len(all_days) - len(work)
    if skipped:
        log(f"resume: skipping {skipped} already-complete day(s); {len(work)} to pull")

    totals = {"done": 0, "empty": 0, "failed": 0}
    expirations_pulled = 0
    quote_rows = 0
    requests = 0
    t0 = monotonic()
    for index, day in enumerate(work, start=1):
        day_t0 = monotonic()
        try:
            result = _backfill_one_day(
                client,
                store,
                ticker=symbol,
                trade_date=day,
                min_dte=min_dte,
                max_dte=max_dte,
                strike_range=strike_range,
                start_time=start_time,
                end_time=end_time,
                interval=interval,
                underlying_source=underlying_source,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
                policy=policy,
                rate_limiter=rate_limiter,
                sleep_fn=sleep_fn,
                log=log,
            )
        except BackfillPermissionError:
            store.upsert_backfill_ledger(
                symbol, day.isoformat(), status="failed", attempts=1, last_error="PERMISSION_DENIED"
            )
            log(f"FATAL: ThetaData denied {day} (needs higher tier). Stopping at {index}/{len(work)}.")
            raise

        store.upsert_backfill_ledger(
            symbol,
            day.isoformat(),
            status=result.status,
            expirations_pulled=result.expirations_pulled,
            quote_rows=result.quote_rows,
            attempts=result.requests,
            last_error=result.last_error,
        )
        totals[result.status] = totals.get(result.status, 0) + 1
        expirations_pulled += result.expirations_pulled
        quote_rows += result.quote_rows
        requests += result.requests

        elapsed = monotonic() - t0
        avg = elapsed / index
        eta_min = (len(work) - index) * avg / 60.0
        log(
            f"[{index}/{len(work)}] {day} status={result.status} exps={result.expirations_pulled} "
            f"rows={result.quote_rows} {monotonic() - day_t0:.1f}s elapsed={elapsed / 60:.1f}m eta~{eta_min:.0f}m"
        )

    return BackfillSummary(
        ticker=symbol,
        start=start,
        end=end,
        trading_days=len(all_days),
        days_attempted=len(work),
        days_done=totals.get("done", 0),
        days_empty=totals.get("empty", 0),
        days_failed=totals.get("failed", 0),
        days_skipped=skipped,
        expirations_pulled=expirations_pulled,
        quote_rows=quote_rows,
        requests=requests,
        elapsed_s=monotonic() - t0,
    )
