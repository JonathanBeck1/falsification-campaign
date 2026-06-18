"""Command-line entrypoint. Subcommands: run-once, schedule, status, kill, unkill."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from trader.adapters.alpaca.market import fetch_intraday_bars as fetch_alpaca_intraday_bars
from trader.adapters.dolthub.options import DoltHubOptionsClient
from trader.adapters.thetadata.options import ThetaDataOptionsClient
from trader.adapters.yahoo.market import fetch_intraday_bars as fetch_yahoo_intraday_bars
from trader.config import get_settings, print_banner_or_die
from trader.enrichment.service import enrich_events
from trader.ingestion.events import fetch_and_persist_events, persist_source_events
from trader.ingestion.source_health import StoreSourceHealthTracker
from trader.notify.discord import build_notifier
from trader.research.cycle import ResearchCycleConfig, ResearchCycleDeps, run_research_cycle
from trader.storage.store import Store

EVENT_SOURCE_NAMES = ("finnhub", "alpaca_news", "yahoo_news", "sec_edgar", "fed", "web_news")
PAPER_INTENT_BRAIN = "PaperIntentEngine"
REPLAY_SAFE_BRAINS = frozenset({
    "BuyAndHoldBrain",
    "ClassicalBrain",
    "ClassicalConservative",
    "ClassicalAggressive",
    "VIXRegimeConservative",
    "VIXRegimeAggressive",
})
REPLAY_SAFE_BRAIN_ORDER = (
    "BuyAndHoldBrain",
    "ClassicalBrain",
    "ClassicalConservative",
    "ClassicalAggressive",
    "VIXRegimeConservative",
    "VIXRegimeAggressive",
)


def _parse_utc_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _empty_source_map() -> dict[str, list]:
    return {source: [] for source in EVENT_SOURCE_NAMES}


def _split_csv(value: str) -> list[str]:
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def _row_get(row, key: str, default=None):
    get = getattr(row, "get", None)
    if get is not None:
        return get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_date_from_row(row) -> date:
    return date.fromisoformat(str(_row_get(row, "trade_date"))[:10])


def _count_orders(store: Store) -> int:
    with store._conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM orders").fetchone()
        return int(row["n"])


def _fetch_one_source_news(
    source: str,
    settings,
    *,
    lookback_days: int | None,
    source_tracker,
) -> dict[str, list]:
    from trader import runner

    finnhub_lookback = lookback_days if lookback_days is not None else 3
    alpaca_lookback = lookback_days if lookback_days is not None else 3
    fed_lookback = lookback_days if lookback_days is not None else 90
    web_lookback = lookback_days if lookback_days is not None else 3
    fetchers = {
        "finnhub": lambda: runner.fetch_news(settings.trader_ticker, lookback_days=finnhub_lookback, limit=15),
        "alpaca_news": lambda: runner.fetch_alpaca_news(
            settings.context_tickers, lookback_days=alpaca_lookback, limit=30
        ),
        "yahoo_news": lambda: runner.fetch_yahoo_news(settings.context_tickers, per_ticker_limit=8),
        "sec_edgar": lambda: (
            runner.fetch_sec_8k_filings(settings.sec_tickers, count_per_ticker=3)
            if getattr(settings, "sec_tickers", None)
            else []
        ),
        "fed": lambda: runner.fetch_fed_press(lookback_days=fed_lookback),
        "web_news": lambda: runner.fetch_web_news(lookback_days=web_lookback),
    }
    by_source = _empty_source_map()
    by_source[source] = runner._safe_fetch_source(source, fetchers[source], heartbeat=source_tracker)
    return by_source


def cmd_run_once(args: argparse.Namespace) -> int:
    print_banner_or_die()
    from trader.runner import run_one_day

    decisions = run_one_day()
    print(f"\nRan {len(decisions)} brains:")
    for name, d in decisions.items():
        print(f"  {name:25s} action={d.action:4s} target={d.target_pct:.0%} conf={d.confidence:.2f}")
    return 0


def cmd_fetch_events(args: argparse.Namespace) -> int:
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    source_tracker = StoreSourceHealthTracker(store, lookback_days=args.lookback_days)
    counts = fetch_and_persist_events(
        store=store,
        ticker=s.trader_ticker,
        context_tickers=s.context_tickers,
        sec_tickers=s.sec_tickers,
        lookback_days=args.lookback_days,
        source_tracker=source_tracker,
    )
    print("Persisted normalized events:")
    for source in sorted(counts):
        print(f"  {source}: {counts[source]}")
    return 0


def cmd_source_health(args: argparse.Namespace) -> int:
    s = get_settings()
    store = Store(s.sqlite_path)
    rows = store.source_fetch_summary(limit=args.limit)
    if not rows:
        print("No source fetches recorded.")
        return 0

    print("Source fetch health:")
    for row in rows:
        print(
            f"  {row['source']:15s} "
            f"status={row['latest_status']} "
            f"items={row['latest_item_count']} "
            f"persisted={row['latest_persisted_count']} "
            f"attempts={row['attempt_count']} "
            f"errors={row['error_count']} "
            f"latest={row['latest_attempted_at']} "
            f"latency_ms={row['latest_latency_ms']}"
        )
        if row.get("latest_error"):
            print(f"    error={row['latest_error']}")
    return 0


def cmd_backfill_events(args: argparse.Namespace) -> int:
    s = get_settings()
    store = Store(s.sqlite_path)
    source_tracker = StoreSourceHealthTracker(store, lookback_days=args.lookback_days)
    if args.source:
        by_source = _fetch_one_source_news(
            args.source,
            s,
            lookback_days=args.lookback_days,
            source_tracker=source_tracker,
        )
        counts = persist_source_events(
            store=store,
            by_source=by_source,
            ticker=s.trader_ticker,
            context_tickers=s.context_tickers,
            source_tracker=source_tracker,
        )
    else:
        counts = fetch_and_persist_events(
            store=store,
            ticker=s.trader_ticker,
            context_tickers=s.context_tickers,
            sec_tickers=s.sec_tickers,
            lookback_days=args.lookback_days,
            source_tracker=source_tracker,
        )
    print("Persisted normalized events:")
    for source in sorted(counts):
        print(f"  {source}: {counts[source]}")
    return 0


def _history_vix_by_date(vix_history) -> dict[str, float]:
    import pandas as pd

    by_date: dict[str, float] = {}
    if vix_history is None or vix_history.empty:
        return by_date
    for index, row in vix_history.iterrows():
        close = row.get("Close")
        if pd.isna(close):
            continue
        by_date[pd.Timestamp(index).date().isoformat()] = float(close)
    return by_date


def _history_rows(history, *, vix_by_date: dict[str, float]) -> list[dict[str, float | str | None]]:
    import pandas as pd

    if history is None or history.empty:
        return []
    rows: list[dict[str, float | str | None]] = []
    for index, row in history.iterrows():
        required = [row.get(column) for column in ("Open", "High", "Low", "Close", "Volume")]
        if any(pd.isna(value) for value in required):
            continue
        trade_date = pd.Timestamp(index).date().isoformat()
        rows.append(
            {
                "trade_date": trade_date,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
                "vix_close": vix_by_date.get(trade_date),
                "yield_curve_10y_2y": None,
            }
        )
    return rows


def cmd_backfill_prices(args: argparse.Namespace) -> int:
    import yfinance

    s = get_settings()
    store = Store(s.sqlite_path)
    tickers = _split_csv(args.tickers)
    if not tickers:
        print("No tickers requested.", file=sys.stderr)
        return 2

    vix_history = yfinance.Ticker("^VIX").history(start=args.start, end=args.end, auto_adjust=False)
    vix_by_date = _history_vix_by_date(vix_history)

    total = 0
    for ticker in tickers:
        history = yfinance.Ticker(ticker).history(start=args.start, end=args.end, auto_adjust=False)
        rows = _history_rows(history, vix_by_date=vix_by_date)
        written = store.upsert_historical_bars(ticker, rows)
        total += written
        print(f"{ticker}: {written} rows")
    print(f"Backfilled historical prices: tickers={len(tickers)} rows={total} vix_days={len(vix_by_date)}")
    return 0


def cmd_options_backfill_dolthub(args: argparse.Namespace) -> int:
    """Backfill free DoltHub EOD options chain/volatility rows."""

    s = get_settings()
    store = Store(s.sqlite_path)
    ticker = args.ticker.strip().upper()
    client = DoltHubOptionsClient()
    try:
        chunks = _date_chunks(args.start, args.end, chunk_days=args.chunk_days)
    except ValueError as exc:
        print(f"Invalid options-backfill arguments: {exc}", file=sys.stderr)
        return 2
    chain_written = 0
    vol_written = 0
    for chunk_start, chunk_end in chunks:
        chain = client.fetch_option_chain(ticker, start=chunk_start, end=chunk_end, limit=args.limit)
        vol_history = client.fetch_volatility_history(ticker, start=chunk_start, end=chunk_end, limit=args.limit)
        chain_written += store.upsert_option_chain_eod(ticker, chain)
        vol_written += store.upsert_option_volatility_history(ticker, vol_history)
    print(
        "DoltHub options backfill: "
        f"ticker={ticker} start={args.start} end={args.end} "
        f"chunks={len(chunks)} option_chain_rows={chain_written} volatility_rows={vol_written}"
    )
    return 0


def cmd_options_backfill_thetadata_quotes(args: argparse.Namespace) -> int:
    """Backfill ThetaData 1-minute option NBBO quote bars (resilient, resumable)."""

    from trader.options.backfill import BackfillPermissionError, run_thetadata_quote_backfill

    try:
        if args.interval != "1m":
            raise ValueError("only --interval 1m is supported by option_quote_bars_1m storage")
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        time.fromisoformat(args.start_time)
        time.fromisoformat(args.end_time)
        if start > end:
            raise ValueError("--start must be on or before --end")
        if args.min_dte < 0 or args.max_dte < args.min_dte:
            raise ValueError("--max-dte must be greater than or equal to --min-dte")
        if args.strike_range < 1:
            raise ValueError("--strike-range must be at least 1")
    except ValueError as exc:
        print(f"Invalid ThetaData quote backfill arguments: {exc}", file=sys.stderr)
        return 2

    s = get_settings()
    store = Store(s.sqlite_path, bulk_load=getattr(args, "bulk_load", False))
    client = ThetaDataOptionsClient(creds_file=s.thetadata_credentials_file)
    try:
        summary = run_thetadata_quote_backfill(
            client,
            store,
            ticker=args.ticker,
            start=start,
            end=end,
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            strike_range=args.strike_range,
            start_time=args.start_time,
            end_time=args.end_time,
            interval=args.interval,
            underlying_source=args.underlying_source,
            risk_free_rate=args.risk_free_rate,
            dividend_yield=args.dividend_yield,
            resume=not args.no_resume,
            force=args.force,
            request_pace_s=args.request_pace_seconds,
            max_retries=args.max_retries,
            request_timeout_s=args.request_timeout_seconds,
        )
    except BackfillPermissionError as exc:
        print(f"ThetaData permission error (request needs a higher subscription tier): {exc}", file=sys.stderr)
        return 1

    print(
        "ThetaData quote backfill: "
        f"ticker={summary.ticker} {summary.start}..{summary.end} "
        f"trading_days={summary.trading_days} attempted={summary.days_attempted} "
        f"done={summary.days_done} empty={summary.days_empty} failed={summary.days_failed} "
        f"skipped={summary.days_skipped} expirations={summary.expirations_pulled} "
        f"rows={summary.quote_rows} requests={summary.requests} elapsed={summary.elapsed_s / 60:.1f}m"
    )
    return 1 if summary.days_failed else 0


def cmd_options_backfill_status(args: argparse.Namespace) -> int:
    """Print the ThetaData backfill ledger summary (resume/progress view)."""
    from collections import Counter

    s = get_settings()
    store = Store(s.sqlite_path)
    ticker = args.ticker.strip().upper()
    rows = store.get_backfill_ledger(ticker, since=args.start, until=args.end)
    by_status = Counter(row["status"] for row in rows)
    dates = [row["trade_date"] for row in rows]
    print(
        "backfill status: "
        f"ticker={ticker} ledger_days={len(rows)} "
        f"done={by_status.get('done', 0)} empty={by_status.get('empty', 0)} failed={by_status.get('failed', 0)} "
        f"quote_rows={sum(row['quote_rows'] for row in rows)} "
        f"range={dates[0] if dates else None}..{dates[-1] if dates else None}"
    )
    failed = [row["trade_date"] for row in rows if row["status"] == "failed"]
    if failed:
        print(f"failed days ({len(failed)}): {', '.join(failed[:20])}{' ...' if len(failed) > 20 else ''}")
    return 0


def cmd_options_intraday_coverage_report(args: argparse.Namespace) -> int:
    """Report coverage/quality over the stored intraday option quote tape."""
    from trader.options.quality import format_intraday_quote_coverage_report, summarize_intraday_quote_coverage

    s = get_settings()
    store = Store(s.sqlite_path)
    coverage = summarize_intraday_quote_coverage(
        store,
        ticker=args.ticker,
        since=args.start,
        until=args.end,
        min_rows_per_day_warning=args.min_rows_per_day_warning,
    )
    report = format_intraday_quote_coverage_report(coverage)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Intraday coverage report written to {output}")
    else:
        print(report)
    return 0


def cmd_options_export_parquet_lake(args: argparse.Namespace) -> int:
    """Export the option_quote_bars_1m firehose to a date-partitioned Parquet lake.

    Reads the SQLite DB READ_ONLY (safe alongside the live backfill) and writes
    Parquet OUTSIDE the SSD DB directory (default: ./lake) so the lake never
    lands next to the large database file.
    """
    import json

    from trader.storage.parquet_export import export_lake

    for d in (args.since, args.until):
        if d:
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                print(f"Invalid date {d!r}: expected YYYY-MM-DD.", file=sys.stderr)
                return 2

    db_path = Path(args.db) if args.db else Path(get_settings().sqlite_path)
    try:
        manifest = export_lake(
            db_path=db_path,
            out_dir=Path(args.out),
            ticker=args.ticker,
            since=args.since,
            until=args.until,
        )
    except Exception as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(manifest, indent=2))
    return 0


def _date_chunks(start: str, end: str, *, chunk_days: int) -> list[tuple[str, str]]:
    if chunk_days < 1:
        raise ValueError("--chunk-days must be at least 1")
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError("--start must be on or before --end")
    chunks: list[tuple[str, str]] = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        chunks.append((current.isoformat(), chunk_end.isoformat()))
        current = chunk_end + timedelta(days=1)
    return chunks


def _underlying_closes_from_store(store: Store, ticker: str, *, since: str, until: str) -> dict[date, float]:
    """Map trade_date -> underlying close from stored historical bars.

    Feeds the shared condor marking core's intrinsic floor / expiration
    settlement on the EOD path. Empty when no bars are backfilled (marking then
    falls back to wing-capped quote debits only).
    """

    closes: dict[date, float] = {}
    for row in store.get_historical_bars(ticker, since=since, until=until):
        close = row.get("close")
        if close is None:
            continue
        closes[date.fromisoformat(str(row["trade_date"])[:10])] = float(close)
    return closes


def cmd_options_backtest_iron_condor(args: argparse.Namespace) -> int:
    """Run the research-only EOD SPY/QQQ iron-condor backtest."""

    from trader.options.backtest import IronCondorBacktestConfig, run_iron_condor_backtest
    from trader.options.iron_condor import IronCondorConfig
    from trader.options.reporting import format_iron_condor_report

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        print(f"Invalid options-backtest arguments: dates must be YYYY-MM-DD ({exc})", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid options-backtest arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    s = get_settings()
    store = Store(s.sqlite_path)
    quotes = store.get_option_chain_eod(ticker, since=args.start, until=args.end)
    if not quotes:
        print(f"No option_chain_eod rows found for {ticker} between {args.start} and {args.end}.", file=sys.stderr)
        return 1

    result = run_iron_condor_backtest(
        quotes,
        IronCondorBacktestConfig(
            ticker=ticker,
            start=start,
            end=end,
            selector=IronCondorConfig(
                min_dte=args.min_dte,
                max_dte=args.max_dte,
                target_delta=args.target_delta,
                wing_width=args.wing_width,
                min_credit=args.min_credit,
            ),
            profit_target_pct=args.profit_target_pct,
            stop_loss_credit_multiple=args.stop_loss_credit_multiple,
            exit_dte=args.exit_dte,
            max_concurrent_trades=args.max_concurrent_trades,
            commission_per_contract=args.commission_per_contract,
            slippage_per_contract=args.slippage_per_contract,
        ),
        underlying_closes=_underlying_closes_from_store(store, ticker, since=args.start, until=args.end),
    )
    store.save_iron_condor_backtest_result(result)
    report = format_iron_condor_report(result)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Iron condor report written to {output}")
    else:
        print(report)
    return 0


def cmd_options_coverage_report(args: argparse.Namespace) -> int:
    from trader.options.quality import format_option_coverage_report, summarize_option_coverage

    s = get_settings()
    store = Store(s.sqlite_path)
    ticker = args.ticker.strip().upper()
    quotes = store.get_option_chain_eod(ticker, since=args.start, until=args.end)
    summary = summarize_option_coverage(quotes, ticker=ticker, min_rows_per_date_warning=args.min_rows_per_date_warning)
    report = format_option_coverage_report(summary)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Options coverage report written to {output}")
    else:
        print(report)
    return 0


def cmd_options_sweep_iron_condor(args: argparse.Namespace) -> int:
    from trader.options.sweep import format_iron_condor_sweep_report, run_iron_condor_sweep

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        wing_widths = _parse_float_csv(args.wing_widths, label="--wing-widths")
        target_deltas = _parse_float_csv(args.target_deltas, label="--target-deltas")
        profit_targets = _parse_float_csv(args.profit_targets, label="--profit-targets")
        stop_loss_multiples = _parse_float_csv(args.stop_loss_multiples, label="--stop-loss-multiples")
    except ValueError as exc:
        print(f"Invalid options-sweep arguments: {exc}", file=sys.stderr)
        return 2
    ticker = args.ticker.strip().upper()
    s = get_settings()
    store = Store(s.sqlite_path)
    quotes = store.get_option_chain_eod(ticker, since=args.start, until=args.end)
    if not quotes:
        print(f"No option_chain_eod rows found for {ticker} between {args.start} and {args.end}.", file=sys.stderr)
        return 1
    rows = run_iron_condor_sweep(
        quotes,
        ticker=ticker,
        start=start,
        end=end,
        wing_widths=wing_widths,
        target_deltas=target_deltas,
        profit_targets=profit_targets,
        stop_loss_multiples=stop_loss_multiples,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        exit_dte=args.exit_dte,
        commission_per_contract=args.commission_per_contract,
        slippage_per_contract=args.slippage_per_contract,
        underlying_closes=_underlying_closes_from_store(store, ticker, since=args.start, until=args.end),
    )
    report = format_iron_condor_sweep_report(rows, ticker=ticker)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Iron condor sweep report written to {output}")
    else:
        print(report)
    return 0


def _build_quote_source(args: argparse.Namespace) -> Any:
    """Construct the day-at-a-time QuoteSource selected by --source/--lake-path.

    Defaults to the SQLite-backed source (unchanged behavior). The lake source
    reads from a date-partitioned Parquet lake so a backtest only touches the
    partitions it needs.
    """
    from trader.options.sources import LakeQuoteSource, SqliteQuoteSource

    source_kind = getattr(args, "source", "sqlite")
    if source_kind == "lake":
        lake_path = getattr(args, "lake_path", None)
        if not lake_path:
            raise ValueError("--lake-path is required when --source lake is used.")
        return LakeQuoteSource(lake_path)
    return SqliteQuoteSource(Store(get_settings().sqlite_path))


def _peek_quote_day_stream(
    source: Any,
    *,
    ticker: str,
    start: date,
    end: date,
) -> Any | None:
    """Return a chronological (trade_date, bars) stream, or None if the window is empty.

    Pulls only the first populated day to detect emptiness so the caller never
    materializes the whole window.
    """
    import itertools

    day_iter = source.iter_days(ticker, start, end)
    first = next(day_iter, None)
    if first is None:
        return None
    return itertools.chain([first], day_iter)


def cmd_options_backtest_intraday_iron_condor(args: argparse.Namespace) -> int:
    """Run a ThetaData-style intraday iron-condor backtest from stored quote bars."""

    from trader.options.intraday import (
        IntradayIronCondorBacktestConfig,
        IntradayIronCondorSelectorConfig,
        format_intraday_iron_condor_report,
        run_intraday_iron_condor_backtest,
    )

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        time.fromisoformat(args.entry_time)
    except ValueError as exc:
        print(f"Invalid intraday options-backtest arguments: {exc}", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid intraday options-backtest arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    try:
        source = _build_quote_source(args)
    except ValueError as exc:
        print(f"Invalid intraday options-backtest arguments: {exc}", file=sys.stderr)
        return 2
    day_stream = _peek_quote_day_stream(source, ticker=ticker, start=start, end=end)
    if day_stream is None:
        print(f"No option_quote_bars_1m rows found for {ticker} between {args.start} and {args.end}.", file=sys.stderr)
        return 1

    result = run_intraday_iron_condor_backtest(
        day_stream,
        IntradayIronCondorBacktestConfig(
            ticker=ticker,
            start=start,
            end=end,
            selector=IntradayIronCondorSelectorConfig(
                min_dte=args.min_dte,
                max_dte=args.max_dte,
                wing_width=args.wing_width,
                max_wing_width=args.max_wing_width,
                selection_mode=args.selection_mode,
                target_short_bid=args.target_short_bid,
                target_delta=args.target_delta,
                max_delta_deviation=args.max_delta_deviation,
                min_credit=args.min_credit,
                min_credit_to_wing_ratio=args.min_credit_ratio,
                max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
                risk_free_rate=args.risk_free_rate,
                dividend_yield=args.dividend_yield,
            ),
            entry_time=args.entry_time,
            profit_target_pct=args.profit_target_pct,
            stop_loss_credit_multiple=args.stop_loss_credit_multiple,
            exit_dte=args.exit_dte,
            max_concurrent_trades=args.max_concurrent_trades,
            commission_per_contract=args.commission_per_contract,
            slippage_per_contract=args.slippage_per_contract,
            exit_decision_time=args.exit_decision_time,
        ),
    )
    Store(get_settings().sqlite_path).save_intraday_iron_condor_backtest_result(result)
    report = format_intraday_iron_condor_report(result)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Intraday iron condor report written to {output}")
    else:
        print(report)
    return 0


def cmd_options_diagnose_intraday_iron_condor(args: argparse.Namespace) -> int:
    """Explain why intraday iron-condor entries did or did not open."""

    from trader.options.intraday import IntradayIronCondorSelectorConfig
    from trader.options.intraday_diagnostics import (
        diagnose_intraday_selection_streaming,
        format_intraday_selection_report,
    )

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        time.fromisoformat(args.entry_time)
    except ValueError as exc:
        print(f"Invalid intraday diagnostics arguments: {exc}", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid intraday diagnostics arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    try:
        source = _build_quote_source(args)
    except ValueError as exc:
        print(f"Invalid intraday diagnostics arguments: {exc}", file=sys.stderr)
        return 2

    diagnostics = diagnose_intraday_selection_streaming(
        source,
        ticker=ticker,
        start=start,
        end=end,
        entry_time=args.entry_time,
        selector=IntradayIronCondorSelectorConfig(
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            wing_width=args.wing_width,
            max_wing_width=args.max_wing_width,
            selection_mode=args.selection_mode,
            target_short_bid=args.target_short_bid,
            target_delta=args.target_delta,
            max_delta_deviation=args.max_delta_deviation,
            min_credit=args.min_credit,
            max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
            risk_free_rate=args.risk_free_rate,
            dividend_yield=args.dividend_yield,
        ),
    )
    report = format_intraday_selection_report(diagnostics)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Intraday selection diagnostics written to {output}")
    else:
        print(report)
    return 0


def cmd_options_sweep_intraday_iron_condor(args: argparse.Namespace) -> int:
    """Run an intraday iron-condor parameter sweep from stored quote bars."""

    from trader.options.intraday_sweep import (
        format_intraday_iron_condor_sweep_report,
        run_intraday_iron_condor_sweep,
    )

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        entry_times = _parse_string_csv(args.entry_times, label="--entry-times")
        for entry_time in entry_times:
            time.fromisoformat(entry_time)
        wing_widths = _parse_float_csv(args.wing_widths, label="--wing-widths")
        target_deltas = _parse_float_csv(args.target_deltas, label="--target-deltas")
        target_short_bids = _parse_float_csv(args.target_short_bids, label="--target-short-bids")
        profit_targets = _parse_float_csv(args.profit_targets, label="--profit-targets")
        stop_loss_multiples = _parse_float_csv(args.stop_loss_multiples, label="--stop-loss-multiples")
    except ValueError as exc:
        print(f"Invalid intraday options-sweep arguments: {exc}", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid intraday options-sweep arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    # FAST screening mode: materialize only the decision-relevant minute bars (market
    # open/close + entry times + exit-decision time) and near-money strikes, pushed
    # down into DuckDB. ~100-200x faster; preserves the trade structure and verdict but
    # NOT the exact P&L (confirm finalists with a full-resolution backtest).
    if getattr(args, "fast", False):
        if args.source != "lake" or not args.lake_path:
            print("--fast requires --source lake and --lake-path.", file=sys.stderr)
            return 2
        from trader.storage.parquet_lake import ParquetLake

        times = sorted({"09:30:00", "16:00:00", args.exit_decision_time, *entry_times} - {""})
        quotes = ParquetLake(args.lake_path).get_decision_bars(
            ticker,
            since=args.start,
            until=args.end,
            times=times,
            strike_band=args.fast_strike_band,
            dte_lo=max(0, args.exit_dte - 2),
            dte_hi=args.max_dte + 2,
        )
    else:
        try:
            source = _build_quote_source(args)
        except ValueError as exc:
            print(f"Invalid intraday options-sweep arguments: {exc}", file=sys.stderr)
            return 2
        # Reuses one in-memory replay tape across every parameter combo.
        quotes = [bar for _trade_date, day_bars in source.iter_days(ticker, start, end) for bar in day_bars]
    if not quotes:
        print(f"No option_quote_bars_1m rows found for {ticker} between {args.start} and {args.end}.", file=sys.stderr)
        return 1

    rows = run_intraday_iron_condor_sweep(
        quotes,
        ticker=ticker,
        start=start,
        end=end,
        entry_times=entry_times,
        selection_mode=args.selection_mode,
        wing_widths=wing_widths,
        target_deltas=target_deltas,
        target_short_bids=target_short_bids,
        profit_targets=profit_targets,
        stop_loss_multiples=stop_loss_multiples,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        max_wing_width=args.max_wing_width,
        max_delta_deviation=args.max_delta_deviation,
        min_credit=args.min_credit,
        min_credit_to_wing_ratio=args.min_credit_ratio,
        exit_dte=args.exit_dte,
        commission_per_contract=args.commission_per_contract,
        slippage_per_contract=args.slippage_per_contract,
        exit_decision_time=args.exit_decision_time,
        risk_free_rate=args.risk_free_rate,
        dividend_yield=args.dividend_yield,
    )
    report = format_intraday_iron_condor_sweep_report(rows, ticker=ticker)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Intraday iron condor sweep report written to {output}")
    else:
        print(report)
    return 0


def cmd_options_backtest_short_put(args: argparse.Namespace) -> int:
    """Run a cash-secured short-put backtest, streaming quotes day-by-day."""

    from trader.options import metrics as metrics_mod
    from trader.options.benchmark import buy_and_hold_benchmark, closes_from_historical_bars
    from trader.options.reporting import render_metrics_markdown, write_research_report
    from trader.options.short_put import (
        ShortPutBacktestConfig,
        ShortPutSelectorConfig,
        format_short_put_report,
        run_short_put_backtest,
    )

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        time.fromisoformat(args.entry_time)
    except ValueError as exc:
        print(f"Invalid short-put backtest arguments: {exc}", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid short-put backtest arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    try:
        source = _build_quote_source(args)
    except ValueError as exc:
        print(f"Invalid short-put backtest arguments: {exc}", file=sys.stderr)
        return 2
    day_stream = _peek_quote_day_stream(source, ticker=ticker, start=start, end=end)
    if day_stream is None:
        print(f"No option_quote_bars_1m rows found for {ticker} between {args.start} and {args.end}.", file=sys.stderr)
        return 1

    result = run_short_put_backtest(
        day_stream,
        ShortPutBacktestConfig(
            ticker=ticker,
            start=start,
            end=end,
            selector=ShortPutSelectorConfig(
                min_dte=args.min_dte,
                max_dte=args.max_dte,
                selection_mode=args.selection_mode,
                target_short_bid=args.target_short_bid,
                target_delta=args.target_delta,
                max_delta_deviation=args.max_delta_deviation,
                min_credit=args.min_credit,
                max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
                risk_free_rate=args.risk_free_rate,
                dividend_yield=args.dividend_yield,
            ),
            entry_time=args.entry_time,
            profit_target_pct=args.profit_target_pct,
            stop_loss_credit_multiple=args.stop_loss_credit_multiple,
            exit_dte=args.exit_dte,
            max_concurrent_trades=args.max_concurrent_trades,
        ),
    )

    closed = metrics_mod.closed_trades_from_intraday(result)
    metrics = metrics_mod.compute_metrics(
        closed,
        starting_capital=args.starting_capital,
        window_start=start,
        window_end=end,
    )
    # Optional buy-and-hold benchmark from historical_bars (small read; skipped if absent).
    try:
        bars = Store(get_settings().sqlite_path).get_historical_bars(ticker, since=args.start, until=args.end)
    except Exception:
        bars = []
    if bars:
        closes = closes_from_historical_bars(bars, since=start, until=end)
        metrics.update(buy_and_hold_benchmark(closes, strategy_return=float(metrics["total_return"])))

    params = {
        "start": args.start,
        "end": args.end,
        "entry_time": args.entry_time,
        "selection_mode": args.selection_mode,
        "target_short_bid": args.target_short_bid,
        "target_delta": args.target_delta,
        "profit_target_pct": args.profit_target_pct,
        "stop_loss_credit_multiple": args.stop_loss_credit_multiple,
        "exit_dte": args.exit_dte,
        "source": args.source,
    }
    title = f"{ticker} Cash-Secured Short Put"
    if args.output:
        paths = write_research_report(
            output_path=args.output,
            metrics=metrics,
            trades=closed,
            title=title,
            params=params,
            starting_capital=args.starting_capital,
        )
        Path(args.output).with_name(f"{Path(args.output).stem}_trades.md").write_text(
            format_short_put_report(result), encoding="utf-8"
        )
        print(f"Short put report written to {paths['md']} (+ json, equity csv, trades md)")
    else:
        print(render_metrics_markdown(metrics, title=title, params=params))
    return 0


def cmd_options_walkforward_intraday_iron_condor(args: argparse.Namespace) -> int:
    """Walk-forward analysis: sweep on each train fold, score on the unseen test fold."""

    from trader.options.walkforward import (
        build_intraday_evaluate_fn,
        build_intraday_sweep_fn,
        format_walk_forward_report,
        make_walk_forward_folds,
        run_walk_forward,
    )

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
        entry_times = _parse_string_csv(args.entry_times, label="--entry-times")
        for entry_time in entry_times:
            time.fromisoformat(entry_time)
        wing_widths = _parse_float_csv(args.wing_widths, label="--wing-widths")
        target_deltas = _parse_float_csv(args.target_deltas, label="--target-deltas")
        target_short_bids = _parse_float_csv(args.target_short_bids, label="--target-short-bids")
        profit_targets = _parse_float_csv(args.profit_targets, label="--profit-targets")
        stop_loss_multiples = _parse_float_csv(args.stop_loss_multiples, label="--stop-loss-multiples")
    except ValueError as exc:
        print(f"Invalid walk-forward arguments: {exc}", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid walk-forward arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    try:
        folds = make_walk_forward_folds(
            start, end, train_days=args.train_days, test_days=args.test_days, step_days=args.step_days
        )
    except ValueError as exc:
        print(f"Invalid walk-forward arguments: {exc}", file=sys.stderr)
        return 2
    if not folds:
        print("No walk-forward folds fit in the window; widen --start/--end or shrink fold sizes.", file=sys.stderr)
        return 1

    ticker = args.ticker.strip().upper()
    try:
        source = _build_quote_source(args)
    except ValueError as exc:
        print(f"Invalid walk-forward arguments: {exc}", file=sys.stderr)
        return 2

    grids = {
        "entry_times": entry_times,
        "selection_mode": args.selection_mode,
        "wing_widths": wing_widths,
        "target_deltas": target_deltas,
        "target_short_bids": target_short_bids,
        "profit_targets": profit_targets,
        "stop_loss_multiples": stop_loss_multiples,
        "min_dte": args.min_dte,
        "max_dte": args.max_dte,
    }
    results = run_walk_forward(
        folds,
        sweep_fn=build_intraday_sweep_fn(source, ticker=ticker, grids=grids),
        evaluate_fn=build_intraday_evaluate_fn(source, ticker=ticker, min_dte=args.min_dte, max_dte=args.max_dte),
        score_key=args.score_key,
    )
    report = format_walk_forward_report(results, ticker=ticker, score_key=args.score_key)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Walk-forward report written to {output}")
    else:
        print(report)
    return 0


def cmd_options_data_quality_report(args: argparse.Namespace) -> int:
    """Stream option_quote_bars_1m day-by-day and report NBBO data quality."""

    from trader.options.quality import format_nbbo_quality_report, summarize_nbbo_quality

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        print(f"Invalid data-quality arguments: {exc}", file=sys.stderr)
        return 2
    if start > end:
        print("Invalid data-quality arguments: --start must be on or before --end.", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    try:
        source = _build_quote_source(args)
    except ValueError as exc:
        print(f"Invalid data-quality arguments: {exc}", file=sys.stderr)
        return 2

    report = summarize_nbbo_quality(
        source,
        ticker=ticker,
        start=start,
        end=end,
        max_reasonable_spread_pct=args.max_spread_pct,
    )
    rendered = format_nbbo_quality_report(report)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"NBBO quality report written to {output}")
    else:
        print(rendered)
    return 0


def _parse_float_csv(value: str, *, label: str) -> list[float]:
    floats = [float(part.strip()) for part in value.split(",") if part.strip()]
    if not floats:
        raise ValueError(f"{label} must contain at least one number")
    return floats


def _parse_string_csv(value: str, *, label: str) -> list[str]:
    items = [part.strip() for part in value.split(",") if part.strip()]
    if not items:
        raise ValueError(f"{label} must contain at least one value")
    return items


def _split_brains(value: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        name = part.strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def _parse_replay_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD (got {value!r})") from exc


def _historical_bar(row):
    from trader.storage.snapshot import Bar

    trade_day = _trade_date_from_row(row)
    return Bar(
        timestamp=datetime.combine(trade_day, time(21, 0), tzinfo=UTC),
        open=float(_row_get(row, "open")),
        high=float(_row_get(row, "high")),
        low=float(_row_get(row, "low")),
        close=float(_row_get(row, "close")),
        volume=float(_row_get(row, "volume")),
    )


def _build_replay_brains(names: list[str], *, store: Store, settings) -> list:
    from trader.backtesting.baselines.buy_and_hold import BuyAndHoldBrain
    from trader.signals.classical import ClassicalBrain
    from trader.signals.variants import all_phase_variants, build_brain

    variants = {config.name: config for config in all_phase_variants()}
    brains = []
    for name in names:
        if name == "BuyAndHoldBrain":
            brains.append(BuyAndHoldBrain())
        elif name == "ClassicalBrain":
            brains.append(ClassicalBrain())
        else:
            config = variants[name]
            brains.append(
                build_brain(
                    config,
                    store=store,
                    daily_budget_usd=getattr(settings, "trader_llm_daily_budget_usd", 0.0),
                )
            )
    return brains


def cmd_replay(args: argparse.Namespace) -> int:
    from trader import runner
    from trader.storage.snapshot import MacroSnapshot, build_snapshot

    s = get_settings()
    if s.trader_live:
        print("Refusing historical replay while trader live mode is enabled.", file=sys.stderr)
        return 2

    requested_brains = _split_brains(args.brains)
    if not requested_brains:
        print("Replay requires at least one brain.", file=sys.stderr)
        return 2

    unsafe = [name for name in requested_brains if name not in REPLAY_SAFE_BRAINS]
    if unsafe:
        print(
            "Replay requested brain(s) that are not replay-safe: "
            f"{', '.join(unsafe)}. Safe brains: {', '.join(REPLAY_SAFE_BRAIN_ORDER)}",
            file=sys.stderr,
        )
        return 2

    try:
        since = _parse_replay_date(args.since, label="--since")
        until = _parse_replay_date(args.until, label="--until")
    except ValueError as exc:
        print(f"Invalid replay arguments: {exc}", file=sys.stderr)
        return 2
    if since > until:
        print("Invalid replay arguments: --since must be on or before --until.", file=sys.stderr)
        return 2

    ticker = (args.ticker or s.trader_ticker).strip().upper()
    store = Store(s.sqlite_path)
    rows = store.get_historical_bars(ticker, until=until.isoformat())
    if len(rows) < 200:
        print(f"Replay requires at least 200 historical bars for {ticker}; found {len(rows)}.", file=sys.stderr)
        return 2

    row_dates = [_trade_date_from_row(row) for row in rows]
    selected = [(idx, row) for idx, row in enumerate(rows) if since <= row_dates[idx] <= until]
    if not selected:
        print(f"No historical bars found for {ticker} between {since} and {until}.", file=sys.stderr)
        return 1
    if selected[0][0] < 199:
        print(
            "Replay requires at least 200 historical bars before and including the first replay day.",
            file=sys.stderr,
        )
        return 2

    replay_brains = _build_replay_brains(requested_brains, store=store, settings=s)
    bars = [_historical_bar(row) for row in rows]
    orders_before = _count_orders(store)
    original_all_brains = runner.all_brains

    def _replay_all_brains(settings, store=None):
        return replay_brains

    days_run = 0
    decisions_run = 0
    try:
        runner.all_brains = _replay_all_brains
        for idx, row in selected:
            trade_day = row_dates[idx]
            snapshot = build_snapshot(
                ticker=ticker,
                trade_date=trade_day,
                bars=bars[max(0, idx + 1 - 252) : idx + 1],
                news=[],
                macro=MacroSnapshot(
                    vix=_optional_float(_row_get(row, "vix_close")),
                    yield_curve_10y_2y=_optional_float(_row_get(row, "yield_curve_10y_2y")),
                ),
            )
            snapshot.snapshot_id = f"replay:{ticker}:{trade_day.isoformat()}"
            decisions = runner.run_one_day(snapshot, sleep_fn=lambda _: None)
            days_run += 1
            decisions_run += len(decisions)
    finally:
        runner.all_brains = original_all_brains

    orders_after = _count_orders(store)
    print(
        "Replay summary: "
        f"ticker={ticker} days={days_run} brains={len(requested_brains)} "
        f"decisions={decisions_run} orders={orders_after - orders_before}"
    )
    return 0


def cmd_data_status(args: argparse.Namespace) -> int:
    """Print or write a read-only local data coverage report."""
    from trader.research.data_coverage import build_data_coverage, format_data_coverage

    s = get_settings()
    store = Store(s.sqlite_path)
    rendered = format_data_coverage(build_data_coverage(store))
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"Data coverage written to {out_path}")
    else:
        print(rendered)
    return 0


def cmd_replay_report(args: argparse.Namespace) -> int:
    """Write a historical replay report with train/test and cost diagnostics."""
    from trader.research.replay_report import ReplayReportConfig, build_replay_report, format_replay_report

    def _parse_date_arg(value: str, *, label: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise SystemExit(f"Invalid {label}: {value!r} must be YYYY-MM-DD") from exc

    s = get_settings()
    store = Store(s.sqlite_path)
    ticker = (args.ticker or s.trader_ticker).strip().upper()
    since = _parse_date_arg(args.since, label="--since")
    until = _parse_date_arg(args.until, label="--until")
    train_until = _parse_date_arg(args.train_until, label="--train-until") if args.train_until else None
    try:
        report = build_replay_report(
            store,
            ReplayReportConfig(
                ticker=ticker,
                since=since,
                until=until,
                train_until=train_until,
                cost_bps=args.cost_bps,
                baseline=args.baseline,
                min_days=args.min_days,
                starting_cash=s.trader_starting_cash,
            ),
        )
    except ValueError as exc:
        print(f"Invalid replay-report arguments: {exc}", file=sys.stderr)
        return 2

    rendered = format_replay_report(report)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"Replay report written to {out_path}")
    return 0


def cmd_notify_test(args: argparse.Namespace) -> int:
    build_notifier().send(args.title, args.body, error=args.error)
    print("Notification route tested.")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    from trader.scheduler import main as sched_main

    sched_main()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    print(f"SQLite: {s.sqlite_path}")
    print(f"Ticker: {s.trader_ticker}")
    print(f"Mode:   {'LIVE' if s.trader_live else 'PAPER'}")
    print(f"LLM cost today: ${store.llm_cost_today():.4f}")
    print("\nPer-brain equity (latest):")
    for brain in store.list_brains():
        curve = store.get_equity_curve(brain)
        if curve:
            last = curve[-1]
            print(f"  {brain:25s} ${last['equity']:>12,.2f}  ({last['trade_date']})")
        else:
            print(f"  {brain:25s} (no decisions yet)")
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    s = get_settings()
    Path(s.kill_switch_path).touch()
    print(f"Kill switch set: {s.kill_switch_path}")
    return 0


def cmd_unkill(args: argparse.Namespace) -> int:
    s = get_settings()
    p = Path(s.kill_switch_path)
    if p.exists():
        p.unlink()
        print(f"Kill switch cleared: {p}")
    else:
        print(f"No kill switch present at {p}")
    return 0


def cmd_enrich_events(args: argparse.Namespace) -> int:
    from datetime import datetime

    from trader.enrichment.mock import DeterministicEnrichmentLLM
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    since = datetime.fromisoformat(args.since) if args.since else None
    llm = DeterministicEnrichmentLLM() if args.mock_llm else None
    summary = enrich_events(
        store=store,
        llm=llm,
        limit=args.limit,
        since=since,
        source=args.source,
        dry_run=args.dry_run,
        daily_budget_usd=s.trader_llm_daily_budget_usd,
    )
    print(
        "Enrichment summary: "
        f"seen={summary.seen} enriched={summary.enriched} rejected={summary.rejected} "
        f"skipped_budget={summary.skipped_budget} dry_run={summary.dry_run}"
    )
    return 0


def cmd_review_events(args: argparse.Namespace) -> int:
    from trader.enrichment.review import filter_events_for_review, format_review_markdown
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    events = store.get_news_events_parsed(source=args.source, limit=args.limit)
    events = filter_events_for_review(events, only=args.only)
    report = format_review_markdown(events)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Review written to {out_path}")
    return 0


def cmd_seed_events(args: argparse.Namespace) -> int:
    from trader.enrichment.seed import seed_demo_events
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    if not args.demo:
        print("Nothing seeded. Pass --demo to create deterministic local demo events.")
        return 0
    count = seed_demo_events(store, limit=args.limit)
    print(f"Seeded demo events: {count}")
    return 0


def cmd_enrichment_status(args: argparse.Namespace) -> int:
    from trader.enrichment.status import compute_enrichment_status
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    events = store.get_news_events_parsed(source=args.source, limit=args.limit)
    status = compute_enrichment_status(events, llm_cost_today=store.llm_cost_today())
    print(
        "Enrichment status: "
        f"total={status.total} enriched={status.enriched} rejected={status.rejected} "
        f"missing={status.missing} llm_cost_today=${status.llm_cost_today:.4f}"
    )
    return 0


def cmd_score_events(args: argparse.Namespace) -> int:
    from trader.research.event_candidate_report import format_candidate_report
    from trader.research.event_candidates import score_events
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    events = store.get_news_events_parsed(source=args.source, limit=args.limit)
    candidates = score_events(events)
    report = format_candidate_report(candidates)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Candidate report written to {out_path} ({len(candidates)} candidates)")
    return 0


def _risk_gate_from_settings(settings):
    from trader.execution.risk import RiskGate

    return RiskGate(
        max_position_pct=settings.trader_max_position_pct,
        max_daily_loss_pct=settings.trader_max_daily_loss_pct,
        kill_switch_path=Path(settings.kill_switch_path),
    )


def _account_for_paper_intent(store: Store, settings, *, ticker: str, last_price: float):
    from trader.execution.broker import SimBroker
    from trader.execution.risk import AccountState

    sim = SimBroker(
        brain=PAPER_INTENT_BRAIN,
        ticker=ticker,
        store=store,
        starting_cash=settings.trader_starting_cash,
        last_price=last_price,
    )
    equity = sim.equity()
    return AccountState(
        cash=sim.cash(),
        position_qty=sim.position_qty(),
        avg_cost=sim.avg_cost(),
        equity_today=equity,
        equity_session_start=equity,
        day_trades_last_5d=store.count_day_trades_last_n_days(PAPER_INTENT_BRAIN),
    )


def cmd_stage_paper_intents(args: argparse.Namespace) -> int:
    from trader.paper.intents import intent_from_candidate, risk_review_intent
    from trader.research.event_candidates import score_events

    s = get_settings()
    store = Store(s.sqlite_path)
    events = store.get_news_events_parsed(source=args.source, event_type=args.event_type, limit=args.limit)
    candidates = score_events(events)
    risk_gate = _risk_gate_from_settings(s)
    staged = blocked = skipped = 0
    for candidate in candidates[: args.limit]:
        intent = intent_from_candidate(
            candidate,
            min_abs_score=args.min_score,
            long_target_pct=args.long_target_pct,
            short_target_pct=args.short_target_pct,
        )
        if intent is None:
            continue
        account = _account_for_paper_intent(store, s, ticker=intent.ticker, last_price=args.last_price)
        reviewed = risk_review_intent(intent, risk_gate=risk_gate, account=account, last_price=args.last_price)
        store.save_paper_trade_intent(reviewed)
        if reviewed.risk_status == "approved":
            staged += 1
        elif reviewed.risk_status == "blocked":
            blocked += 1
        else:
            skipped += 1

    print(f"Paper intents: staged={staged} blocked={blocked} skipped={skipped}")
    return 0


def cmd_simulate_paper_intents(args: argparse.Namespace) -> int:
    from trader.execution.broker import SimBroker

    s = get_settings()
    if s.trader_live:
        print("Refusing to simulate paper intents while TRADER_LIVE=true")
        return 1
    store = Store(s.sqlite_path)
    rows = [
        row
        for row in store.list_paper_trade_intents(limit=args.limit * 5)
        if row["status"] == "staged"
        and row["risk_status"] == "approved"
        and row["final_action"] in {"BUY", "SELL"}
        and float(row["final_qty"] or 0) > 0
    ][: args.limit]
    simulated = skipped = 0
    for row in rows:
        sim = SimBroker(
            brain=PAPER_INTENT_BRAIN,
            ticker=row["ticker"],
            store=store,
            starting_cash=s.trader_starting_cash,
            last_price=args.last_price,
        )
        try:
            fill = sim.fill_at_market(
                side="buy" if row["final_action"] == "BUY" else "sell",
                qty=float(row["final_qty"]),
                price=args.last_price,
                decision_id=None,
            )
        except Exception:
            store.update_paper_trade_intent_status(row["intent_id"], "skipped")
            skipped += 1
            continue
        store.update_paper_trade_intent_status(row["intent_id"], "simulated", simulated_order_id=fill.client_order_id)
        simulated += 1

    print(f"Paper intents simulated: simulated={simulated} skipped={skipped}")
    return 0


def cmd_similar_events(args: argparse.Namespace) -> int:
    from datetime import datetime

    from trader.research.event_retrieval import (
        RetrievalFilters,
        format_retrieval_report,
        retrieve_relevant_events,
    )
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    query = store.get_news_event_parsed(args.event_id)
    if query is None:
        print(f"No event found for event_id={args.event_id}")
        return 1
    as_of = datetime.fromisoformat(args.as_of)
    filters = RetrievalFilters(
        event_types=[args.event_type] if args.event_type else None,
        sources=[args.source] if args.source else None,
    )
    hits = retrieve_relevant_events(
        store=store,
        query=query,
        as_of=as_of,
        k=args.k,
        min_candidates=args.min_candidates,
        filters=filters,
        log_retrieval=not args.no_log,
    )
    report = format_retrieval_report(hits, query=query, as_of=as_of)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Similar-events report written to {out_path} ({len(hits)} hits)")
    return 0


def cmd_candidate_context(args: argparse.Namespace) -> int:
    from datetime import datetime

    from trader.research.candidate_context_report import (
        build_candidate_contexts,
        format_candidate_context_report,
    )
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)
    as_of = datetime.fromisoformat(args.as_of)
    events = store.get_news_events_parsed(source=args.source, limit=args.event_limit)
    contexts = build_candidate_contexts(
        store=store,
        events=events,
        as_of=as_of,
        candidate_limit=args.candidate_limit,
        hits_per_candidate=args.hits_per_candidate,
        min_candidates=args.min_candidates,
        log_retrieval=not args.no_log,
    )
    report = format_candidate_context_report(contexts, as_of=as_of)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Candidate-context report written to {out_path} ({len(contexts)} candidates)")
    return 0


def cmd_run_scenario(args: argparse.Namespace) -> int:
    """Run a sample news scenario through ThesisEngine + Aggregator.

    Demonstrates how the system would react to a real-world news situation
    using manual labels. Outputs a markdown report.
    """
    from trader.scenarios import SCENARIO_NAMES, SCENARIOS, build_scenario_events
    from trader.thesis import ThesisAggregator, ThesisEngine
    from trader.thesis.scenario_report import render_scenario_report

    if args.scenario not in SCENARIOS:
        print(f"Unknown scenario '{args.scenario}'. Available:")
        for n in SCENARIO_NAMES:
            print(f"  - {n}")
        return 1

    scenario = SCENARIOS[args.scenario]
    engine = ThesisEngine()
    aggregator = ThesisAggregator()

    events_with_times = build_scenario_events(scenario)
    report = render_scenario_report(scenario, events_with_times, engine, aggregator)

    out_path = Path(args.output) if args.output else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"Scenario report written to {out_path}")
    else:
        print(report)
    return 0


def cmd_research_events(args: argparse.Namespace) -> int:
    """Event-window research study per brain/09."""
    from datetime import datetime, timedelta

    from trader.backtesting.event_window import (
        aggregate_by_type,
        compute_event_returns,
        format_report,
    )
    from trader.storage.store import Store

    s = get_settings()
    store = Store(s.sqlite_path)

    since = datetime.fromisoformat(args.since) if args.since else None
    until = datetime.fromisoformat(args.until) if args.until else None
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None

    events = store.get_news_events_parsed(
        since=since,
        until=until,
        as_of=as_of,
        source=args.source,
        event_type=args.event_type,
    )
    if not events:
        print("No events found in the selected window.")
        return 0

    start = min(e.observed_at for e in events) - timedelta(minutes=30)
    end = max(e.observed_at for e in events) + timedelta(days=6)
    print(
        f"Fetching {args.benchmark} {args.minutes}m bars via {args.data_provider} from "
        f"{start.isoformat()} to {end.isoformat()} for {len(events)} events ..."
    )
    if args.data_provider == "alpaca":
        bars = fetch_alpaca_intraday_bars(args.benchmark, start, end, minutes=args.minutes)
    else:
        bars = fetch_yahoo_intraday_bars(args.benchmark, start, end, minutes=args.minutes)
    print(f"  got {len(bars)} bars")

    results = compute_event_returns(events, bars, benchmark=args.benchmark)
    stats = aggregate_by_type(results)
    report = format_report(
        stats,
        benchmark=args.benchmark,
        metadata={
            "events": len(events),
            "bars": len(bars),
            "source": args.source or "all",
            "event_type": args.event_type or "all",
            "as_of": as_of.isoformat() if as_of else "not specified",
            "minutes": args.minutes,
            "data_provider": args.data_provider,
        },
    )

    out_path = Path(args.output) if args.output else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"Report written to {out_path}")
    else:
        print(report)
    return 0


def cmd_outcome_backtest(args: argparse.Namespace) -> int:
    """Yahoo-backed event outcome backtest."""
    from datetime import timedelta

    from trader.backtesting.outcomes import (
        EntryTimeMode,
        OutcomeConfig,
        compute_outcomes,
        event_entry_time,
        format_outcome_report,
        parse_group_by,
        parse_horizons,
    )
    from trader.storage.store import Store

    try:
        since = _parse_utc_datetime(args.since)
        until = _parse_utc_datetime(args.until)
        entry_mode = EntryTimeMode(args.entry_time)
        groups = parse_group_by(args.group_by)
        horizons = parse_horizons(args.horizons)
    except ValueError as exc:
        print(f"Invalid outcome-backtest arguments: {exc}")
        return 2

    s = get_settings()
    store = Store(s.sqlite_path)

    events = store.get_news_events_parsed(source=args.source, event_type=args.event_type, limit=args.limit)
    if not events:
        print("No events found in the selected window.")
        return 0

    event_entries = [
        (event, entry_time)
        for event in events
        if (entry_time := event_entry_time(event, entry_mode)) is not None
    ]
    if not event_entries:
        print(f"No events have a usable {entry_mode.value} entry timestamp.")
        return 0

    event_entries = [
        (event, entry_time)
        for event, entry_time in event_entries
        if (since is None or entry_time >= since) and (until is None or entry_time < until)
    ]
    if not event_entries:
        print("No events found in the selected window.")
        return 0

    events = [event for event, _entry_time in event_entries]
    entry_times = [entry_time for _event, entry_time in event_entries]
    start = min(entry_times) - timedelta(minutes=30)
    max_horizon = max(horizons.values())
    end = max(entry_times) + max_horizon
    if max_horizon >= timedelta(days=1):
        end += timedelta(days=4)
    bars = fetch_yahoo_intraday_bars(args.benchmark, start, end, minutes=args.minutes)
    if not bars:
        print("No bars returned from Yahoo.")
        return 1

    config = OutcomeConfig(
        benchmark=args.benchmark,
        entry_time=entry_mode,
        horizons=horizons,
        group_by=groups,
        min_sample=args.min_sample,
    )
    run = compute_outcomes(events, bars, config)
    metadata = {
        "events": len(events),
        "bars": len(bars),
        "source": args.source or "all",
        "event_type": args.event_type or "all",
        "minutes": args.minutes,
        "data_provider": "yahoo",
        "fetch_start": start.isoformat(),
        "fetch_end": end.isoformat(),
    }
    if since is not None:
        metadata["since"] = since.isoformat()
    if until is not None:
        metadata["until"] = until.isoformat()

    report = format_outcome_report(run, config=config, metadata=metadata)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Outcome report written to {out_path}")
    return 0


def cmd_outcome_review(args: argparse.Namespace) -> int:
    """Review a generated outcome-backtest Markdown report."""
    from trader.research.outcome_review import (
        format_outcome_review,
        parse_outcome_report,
        review_outcomes,
    )

    if args.min_sample < 1:
        print("Invalid outcome-review arguments: min_sample must be at least 1")
        return 2

    input_path = Path(args.outcome_report)
    if not input_path.exists():
        print(f"Outcome report not found: {input_path}")
        return 1

    try:
        data = parse_outcome_report(input_path.read_text())
        review = review_outcomes(data, min_sample=args.min_sample, focus_horizon=args.focus_horizon)
    except ValueError as exc:
        print(f"Invalid outcome report: {exc}")
        return 1

    rendered = format_outcome_review(review)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered)
    print(f"Outcome review written to {out_path}")
    return 0


def cmd_edge_report(args: argparse.Namespace) -> int:
    """Generate a research-only edge validation report from outcome stats."""
    from trader.research.edge_report import build_edge_rows_from_outcome_report, format_edge_report

    if args.min_n < 1:
        print("Invalid edge-report arguments: min_n must be at least 1")
        return 2
    if args.cost_bps < 0:
        print("Invalid edge-report arguments: cost_bps must be non-negative")
        return 2

    input_path = Path(args.outcome_report)
    if not input_path.exists():
        print(f"Outcome report not found: {input_path}")
        return 1

    try:
        rows = build_edge_rows_from_outcome_report(
            input_path.read_text(encoding="utf-8"),
            min_n=args.min_n,
            cost_bps=args.cost_bps,
        )
    except ValueError as exc:
        print(f"Invalid outcome report: {exc}")
        return 1

    rendered = format_edge_report(
        rows,
        source_path=str(input_path),
        min_n=args.min_n,
        cost_bps=args.cost_bps,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"Edge report written to {out_path}")
    return 0


def cmd_research_cycle(args: argparse.Namespace) -> int:
    """Run the repeatable research evidence loop and write a manifest."""
    from datetime import timedelta

    from trader.backtesting.outcomes import (
        EntryTimeMode,
        OutcomeConfig,
        compute_outcomes,
        event_entry_time,
        format_outcome_report,
        parse_group_by,
        parse_horizons,
    )
    from trader.enrichment.mock import DeterministicEnrichmentLLM
    from trader.research.candidate_context_report import (
        build_candidate_contexts,
        format_candidate_context_report,
    )
    from trader.research.event_candidate_report import format_candidate_report
    from trader.research.event_candidates import score_events
    from trader.research.outcome_review import format_outcome_review, parse_outcome_report, review_outcomes

    try:
        since = _parse_utc_datetime(args.since)
        until = _parse_utc_datetime(args.until)
        entry_mode = EntryTimeMode(args.entry_time)
        group_by = parse_group_by(args.group_by)
        horizons = parse_horizons(args.horizons)
    except ValueError as exc:
        print(f"Invalid research-cycle arguments: {exc}")
        return 2

    s = get_settings()
    store = Store(s.sqlite_path)
    reports_dir = Path(args.reports_dir)
    source_tracker = StoreSourceHealthTracker(store, lookback_days=args.lookback_days)

    def fetch_step() -> dict[str, int]:
        return fetch_and_persist_events(
            store=store,
            ticker=s.trader_ticker,
            context_tickers=s.context_tickers,
            sec_tickers=s.sec_tickers,
            lookback_days=args.lookback_days,
            source_tracker=source_tracker,
        )

    def enrich_step() -> tuple[int, int]:
        summary = enrich_events(
            store=store,
            llm=DeterministicEnrichmentLLM() if args.mock_llm else None,
            limit=args.enrich_limit,
            source=args.source,
            dry_run=False,
            daily_budget_usd=s.trader_llm_daily_budget_usd,
        )
        return (summary.enriched, summary.rejected)

    def score_step(output: Path) -> int:
        events = store.get_news_events_parsed(source=args.source, event_type=args.event_type, limit=args.limit)
        candidates = score_events(events)
        output.write_text(format_candidate_report(candidates), encoding="utf-8")
        return len(candidates)

    def context_step(output: Path) -> int:
        as_of = _parse_utc_datetime(args.as_of) or datetime.now(UTC)
        events = store.get_news_events_parsed(source=args.source, event_type=args.event_type, limit=args.limit)
        contexts = build_candidate_contexts(
            store=store,
            events=events,
            as_of=as_of,
            candidate_limit=args.candidate_limit,
            hits_per_candidate=args.hits_per_candidate,
            min_candidates=args.min_candidates,
        )
        output.write_text(format_candidate_context_report(contexts, as_of=as_of), encoding="utf-8")
        return len(contexts)

    def outcome_step(output: Path) -> None:
        events = store.get_news_events_parsed(source=args.source, event_type=args.event_type, limit=args.limit)
        event_entries = [
            (event, entry_time)
            for event in events
            if (entry_time := event_entry_time(event, entry_mode)) is not None
        ]
        event_entries = [
            (event, entry_time)
            for event, entry_time in event_entries
            if (since is None or entry_time >= since) and (until is None or entry_time < until)
        ]

        config = OutcomeConfig(
            benchmark=args.benchmark,
            entry_time=entry_mode,
            horizons=horizons,
            group_by=group_by,
            min_sample=args.min_sample,
        )
        metadata: dict[str, object] = {
            "source": args.source or "all",
            "event_type": args.event_type or "all",
            "minutes": args.minutes,
            "data_provider": "yahoo",
        }
        if since is not None:
            metadata["since"] = since.isoformat()
        if until is not None:
            metadata["until"] = until.isoformat()

        if event_entries:
            entry_times = [entry_time for _event, entry_time in event_entries]
            start = min(entry_times) - timedelta(minutes=30)
            max_horizon = max(horizons.values())
            end = max(entry_times) + max_horizon
            if max_horizon >= timedelta(days=1):
                end += timedelta(days=4)
            bars = fetch_yahoo_intraday_bars(args.benchmark, start, end, minutes=args.minutes)
            if not bars:
                raise RuntimeError("No bars returned from Yahoo for research-cycle outcome step")
            metadata.update(
                {
                    "events": len(event_entries),
                    "bars": len(bars),
                    "fetch_start": start.isoformat(),
                    "fetch_end": end.isoformat(),
                }
            )
            run = compute_outcomes([event for event, _entry_time in event_entries], bars, config)
        else:
            metadata.update({"events": 0, "bars": 0})
            run = compute_outcomes([], [], config)

        output.write_text(format_outcome_report(run, config=config, metadata=metadata), encoding="utf-8")

    def review_step(input_path: Path, output: Path) -> None:
        data = parse_outcome_report(input_path.read_text(encoding="utf-8"))
        review = review_outcomes(data, min_sample=args.min_sample, focus_horizon=args.focus_horizon)
        output.write_text(format_outcome_review(review), encoding="utf-8")

    result = run_research_cycle(
        store=store,
        config=ResearchCycleConfig(
            reports_dir=reports_dir,
            benchmark=args.benchmark,
            entry_time=args.entry_time,
            horizons=args.horizons,
            group_by=",".join(group_by),
            since=since.isoformat() if since else None,
            until=until.isoformat() if until else None,
            data_provider="yahoo",
            mock_llm=args.mock_llm,
            fetch_first=not args.skip_fetch,
            candidate_context=args.candidate_context,
        ),
        deps=ResearchCycleDeps(
            fetch_events=fetch_step,
            enrich=enrich_step,
            score=score_step,
            candidate_context=context_step,
            outcome_backtest=outcome_step,
            outcome_review=review_step,
        ),
        notifier=build_notifier(),
    )
    print(f"Research cycle {result.status}: {result.run_id}")
    print(f"Manifest: {result.manifest_path}")
    if result.error:
        print(f"Error: {result.error}")
    return 0 if result.status == "succeeded" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trader")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run-once", help="Fetch today's snapshot and run all brains once.").set_defaults(func=cmd_run_once)

    fetch_events = sub.add_parser(
        "fetch-events", help="Fetch and persist normalized events without running signals."
    )
    fetch_events.add_argument(
        "--lookback-days",
        dest="lookback_days",
        type=int,
        default=None,
        help=(
            "Override the per-source lookback window (applies to finnhub, alpaca_news, fed, web_news; "
            "yahoo/sec ignore it). Default keeps each source's own default."
        ),
    )
    fetch_events.set_defaults(func=cmd_fetch_events)
    source_health = sub.add_parser("source-health", help="Show recent source fetch quality and errors.")
    source_health.add_argument("--limit", type=int, default=20, help="Maximum source summaries to show.")
    source_health.set_defaults(func=cmd_source_health)

    backfill_events = sub.add_parser("backfill-events", help="Fetch and persist events with source health tracking.")
    backfill_events.add_argument("--source", choices=EVENT_SOURCE_NAMES, help="Only backfill one event source.")
    backfill_events.add_argument(
        "--lookback-days",
        dest="lookback_days",
        type=int,
        default=None,
        help=(
            "Override the per-source lookback window (applies to finnhub, alpaca_news, fed, web_news; "
            "yahoo/sec ignore it). Default keeps each source's own default."
        ),
    )
    backfill_events.set_defaults(func=cmd_backfill_events)

    backfill_prices = sub.add_parser("backfill-prices", help="Backfill daily OHLCV and VIX data from Yahoo Finance.")
    backfill_prices.add_argument("--start", required=True, help="Start date (YYYY-MM-DD).")
    backfill_prices.add_argument("--end", required=True, help="End date (YYYY-MM-DD).")
    backfill_prices.add_argument(
        "--tickers",
        default="QQQ,SPY",
        help="Comma-separated tickers to backfill (default: QQQ,SPY).",
    )
    backfill_prices.set_defaults(func=cmd_backfill_prices)

    options_backfill = sub.add_parser(
        "options-backfill-dolthub",
        help="Backfill free DoltHub EOD option chains and volatility history into SQLite.",
    )
    options_backfill.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_backfill.add_argument("--start", required=True, help="Start date YYYY-MM-DD.")
    options_backfill.add_argument("--end", required=True, help="End date YYYY-MM-DD.")
    options_backfill.add_argument("--limit", type=int, default=100_000, help="Maximum rows per DoltHub table query.")
    options_backfill.add_argument(
        "--chunk-days",
        type=int,
        default=1,
        help="Split DoltHub SQL reads into N-day chunks to avoid server query deadlines (default: 1).",
    )
    options_backfill.set_defaults(func=cmd_options_backfill_dolthub)

    options_thetadata = sub.add_parser(
        "options-backfill-thetadata-quotes",
        help="Backfill ThetaData 1-minute option NBBO quote bars into SQLite.",
    )
    options_thetadata.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_thetadata.add_argument("--start", required=True, help="Start date YYYY-MM-DD.")
    options_thetadata.add_argument("--end", required=True, help="End date YYYY-MM-DD.")
    options_thetadata.add_argument(
        "--min-dte",
        type=int,
        default=18,
        help="Min DTE to pull (default 18 = buffer below the 21-DTE exit so held positions stay markable).",
    )
    options_thetadata.add_argument(
        "--max-dte", type=int, default=48, help="Max DTE to pull (default 48; strategy entry is 30-45)."
    )
    options_thetadata.add_argument(
        "--start-time",
        default="09:30:00",
        help="Market-session start time for quote pulls (HH:MM:SS, default: 09:30:00).",
    )
    options_thetadata.add_argument(
        "--end-time",
        default="16:00:00",
        help="Market-session end time for quote pulls (HH:MM:SS, default: 16:00:00).",
    )
    options_thetadata.add_argument("--interval", default="1m", help="ThetaData quote interval. Only 1m is stored.")
    options_thetadata.add_argument(
        "--strike-range",
        type=int,
        default=60,
        help="ThetaData strike_range around spot for each expiration request (default: 60).",
    )
    options_thetadata.add_argument(
        "--underlying-source",
        choices=("parity", "stock", "none"),
        default="parity",
        help=(
            "How to attach underlying spot. Default parity works on ThetaData Options Value; "
            "stock requires stock-data entitlement."
        ),
    )
    options_thetadata.add_argument("--risk-free-rate", type=float, default=0.04)
    options_thetadata.add_argument("--dividend-yield", type=float, default=0.0)
    options_thetadata.add_argument(
        "--request-pace-seconds",
        type=float,
        default=2.1,
        help="Min seconds between ThetaData requests (Value tier = 30 req/min; default 2.1).",
    )
    options_thetadata.add_argument(
        "--max-retries", type=int, default=4, help="Retries per request on transient errors (default 4)."
    )
    options_thetadata.add_argument(
        "--request-timeout-seconds", type=float, default=30.0, help="Per-request timeout before retry (default 30)."
    )
    options_thetadata.add_argument("--no-resume", action="store_true", help="Re-pull days already in the ledger.")
    options_thetadata.add_argument("--force", action="store_true", help="Ignore ledger; pull every day in range.")
    options_thetadata.add_argument(
        "--bulk-load",
        action="store_true",
        help="Faster writes for large backfills: batch each day's inserts into a "
        "single transaction + relaxed durability PRAGMAs (crash-safe under WAL). "
        "Recommended for multi-year pulls, especially on external SSDs.",
    )
    options_thetadata.set_defaults(func=cmd_options_backfill_thetadata_quotes)

    options_backfill_status = sub.add_parser(
        "options-backfill-status",
        help="Show the ThetaData backfill ledger summary (resume/progress).",
    )
    options_backfill_status.add_argument("--ticker", default="SPY")
    options_backfill_status.add_argument("--start", default=None, help="Optional start date YYYY-MM-DD.")
    options_backfill_status.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD.")
    options_backfill_status.set_defaults(func=cmd_options_backfill_status)

    options_intraday_coverage = sub.add_parser(
        "options-intraday-coverage-report",
        help="Coverage/quality report over the stored intraday option quote tape.",
    )
    options_intraday_coverage.add_argument("--ticker", default="SPY")
    options_intraday_coverage.add_argument("--start", default=None, help="Optional start date YYYY-MM-DD.")
    options_intraday_coverage.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD.")
    options_intraday_coverage.add_argument("--min-rows-per-day-warning", type=int, default=5000)
    options_intraday_coverage.add_argument("--output", default=None, help="Optional markdown output path.")
    options_intraday_coverage.set_defaults(func=cmd_options_intraday_coverage_report)

    options_export_lake = sub.add_parser(
        "options-export-parquet-lake",
        help="Export option_quote_bars_1m to a date-partitioned Parquet lake (DuckDB, READ_ONLY).",
    )
    options_export_lake.add_argument(
        "--db",
        default=None,
        help="SQLite DB path (default: settings sqlite_path).",
    )
    options_export_lake.add_argument(
        "--out",
        default="lake",
        help="Output dir for the Parquet lake. Keep this OUTSIDE the SSD DB dir (default: lake).",
    )
    options_export_lake.add_argument("--ticker", default=None, help="Restrict export to one ticker (e.g. QQQ).")
    options_export_lake.add_argument("--since", default=None, help="Only export trade_date >= this (YYYY-MM-DD).")
    options_export_lake.add_argument("--until", default=None, help="Only export trade_date <= this (YYYY-MM-DD).")
    options_export_lake.set_defaults(func=cmd_options_export_parquet_lake)

    options_backtest = sub.add_parser(
        "options-backtest-iron-condor",
        help="Run an EOD research-only iron-condor backtest from stored option_chain_eod rows.",
    )
    options_backtest.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_backtest.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    options_backtest.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    options_backtest.add_argument("--min-dte", type=int, default=30)
    options_backtest.add_argument("--max-dte", type=int, default=45)
    options_backtest.add_argument("--target-delta", type=float, default=0.16)
    options_backtest.add_argument("--wing-width", type=float, default=5.0)
    options_backtest.add_argument("--min-credit", type=float, default=0.05)
    options_backtest.add_argument("--profit-target-pct", type=float, default=0.50)
    options_backtest.add_argument("--stop-loss-credit-multiple", type=float, default=2.0)
    options_backtest.add_argument("--exit-dte", type=int, default=21)
    options_backtest.add_argument("--max-concurrent-trades", type=int, default=1)
    options_backtest.add_argument(
        "--commission-per-contract",
        type=float,
        default=0.65,
        help="Commission per option contract per side (default: 0.65).",
    )
    options_backtest.add_argument(
        "--slippage-per-contract",
        type=float,
        default=0.02,
        help="Option-price points lost crossing the spread per leg, entry and exit (default: 0.02).",
    )
    options_backtest.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    options_backtest.set_defaults(func=cmd_options_backtest_iron_condor)

    options_coverage = sub.add_parser(
        "options-coverage-report",
        help="Write option_chain_eod coverage diagnostics for a ticker/date window.",
    )
    options_coverage.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_coverage.add_argument("--start", help="First trade date YYYY-MM-DD.")
    options_coverage.add_argument("--end", help="Last trade date YYYY-MM-DD.")
    options_coverage.add_argument("--min-rows-per-date-warning", type=int, default=50)
    options_coverage.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    options_coverage.set_defaults(func=cmd_options_coverage_report)

    options_sweep = sub.add_parser(
        "options-sweep-iron-condor",
        help="Run an EOD iron-condor parameter sweep from stored option_chain_eod rows.",
    )
    options_sweep.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_sweep.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    options_sweep.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    options_sweep.add_argument("--min-dte", type=int, default=30)
    options_sweep.add_argument("--max-dte", type=int, default=45)
    options_sweep.add_argument("--exit-dte", type=int, default=21)
    options_sweep.add_argument("--wing-widths", default="5", help="Comma-separated wing widths, e.g. 5,10.")
    options_sweep.add_argument("--target-deltas", default="0.16", help="Comma-separated target deltas.")
    options_sweep.add_argument("--profit-targets", default="0.50", help="Comma-separated profit targets.")
    options_sweep.add_argument("--stop-loss-multiples", default="2.0", help="Comma-separated stop loss credit multiples.")
    options_sweep.add_argument("--commission-per-contract", type=float, default=0.65)
    options_sweep.add_argument("--slippage-per-contract", type=float, default=0.02)
    options_sweep.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    options_sweep.set_defaults(func=cmd_options_sweep_iron_condor)

    options_intraday = sub.add_parser(
        "options-backtest-intraday-iron-condor",
        help="Run an intraday iron-condor backtest from stored option_quote_bars_1m rows.",
    )
    options_intraday.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_intraday.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    options_intraday.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    options_intraday.add_argument("--entry-time", default="09:45:00", help="Entry time HH:MM:SS (default: 09:45:00).")
    options_intraday.add_argument("--min-dte", type=int, default=30)
    options_intraday.add_argument("--max-dte", type=int, default=45)
    options_intraday.add_argument("--wing-width", type=float, default=5.0)
    options_intraday.add_argument("--max-wing-width", type=float, default=20.0)
    options_intraday.add_argument(
        "--selection-mode",
        choices=("premium", "delta"),
        default="premium",
        help="Short-strike selection mode: premium uses target bid; delta estimates Black-Scholes delta from quotes.",
    )
    options_intraday.add_argument("--target-short-bid", type=float, default=1.0)
    options_intraday.add_argument("--target-delta", type=float, default=0.16)
    options_intraday.add_argument("--max-delta-deviation", type=float, default=0.08)
    options_intraday.add_argument("--min-credit", type=float, default=0.05)
    options_intraday.add_argument(
        "--min-credit-ratio",
        type=float,
        default=0.10,
        help="Reject entries whose credit is below this fraction of the wing width (default: 0.10).",
    )
    options_intraday.add_argument("--max-bid-ask-spread-pct", type=float, default=1.0)
    options_intraday.add_argument("--risk-free-rate", type=float, default=0.04)
    options_intraday.add_argument("--dividend-yield", type=float, default=0.0)
    options_intraday.add_argument("--profit-target-pct", type=float, default=0.50)
    options_intraday.add_argument("--stop-loss-credit-multiple", type=float, default=2.0)
    options_intraday.add_argument("--exit-dte", type=int, default=21)
    options_intraday.add_argument("--max-concurrent-trades", type=int, default=1)
    options_intraday.add_argument(
        "--commission-per-contract",
        type=float,
        default=0.65,
        help="Per-contract commission; charged on all 4 legs at open and close (default: 0.65).",
    )
    options_intraday.add_argument(
        "--slippage-per-contract",
        type=float,
        default=0.02,
        help="Option-price slippage per leg, applied on entry and exit fills (default: 0.02).",
    )
    options_intraday.add_argument(
        "--exit-decision-time",
        default="15:55:00",
        help="Only act on profit-target/stop exits at/after this time each day (default: 15:55:00; "
        "set empty to allow every-minute exits).",
    )
    options_intraday.add_argument(
        "--source",
        choices=("sqlite", "lake"),
        default="sqlite",
        help="Quote backend: sqlite (default) or a Parquet lake.",
    )
    options_intraday.add_argument("--lake-path", help="Lake root dir/URL when --source lake is used.")
    options_intraday.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    options_intraday.set_defaults(func=cmd_options_backtest_intraday_iron_condor)

    options_intraday_diag = sub.add_parser(
        "options-diagnose-intraday-iron-condor",
        help="Explain why intraday iron-condor entries did or did not open.",
    )
    options_intraday_diag.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_intraday_diag.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    options_intraday_diag.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    options_intraday_diag.add_argument("--entry-time", default="09:45:00", help="Entry time HH:MM:SS.")
    options_intraday_diag.add_argument("--min-dte", type=int, default=30)
    options_intraday_diag.add_argument("--max-dte", type=int, default=45)
    options_intraday_diag.add_argument("--wing-width", type=float, default=5.0)
    options_intraday_diag.add_argument("--max-wing-width", type=float, default=20.0)
    options_intraday_diag.add_argument("--selection-mode", choices=("premium", "delta"), default="delta")
    options_intraday_diag.add_argument("--target-short-bid", type=float, default=1.0)
    options_intraday_diag.add_argument("--target-delta", type=float, default=0.16)
    options_intraday_diag.add_argument("--max-delta-deviation", type=float, default=0.08)
    options_intraday_diag.add_argument("--min-credit", type=float, default=0.05)
    options_intraday_diag.add_argument("--max-bid-ask-spread-pct", type=float, default=1.0)
    options_intraday_diag.add_argument("--risk-free-rate", type=float, default=0.04)
    options_intraday_diag.add_argument("--dividend-yield", type=float, default=0.0)
    options_intraday_diag.add_argument(
        "--source",
        choices=("sqlite", "lake"),
        default="sqlite",
        help="Quote backend: sqlite (default) or a Parquet lake.",
    )
    options_intraday_diag.add_argument("--lake-path", help="Lake root dir/URL when --source lake is used.")
    options_intraday_diag.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    options_intraday_diag.set_defaults(func=cmd_options_diagnose_intraday_iron_condor)

    options_intraday_sweep = sub.add_parser(
        "options-sweep-intraday-iron-condor",
        help="Run an intraday iron-condor parameter sweep from stored option_quote_bars_1m rows.",
    )
    options_intraday_sweep.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    options_intraday_sweep.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    options_intraday_sweep.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    options_intraday_sweep.add_argument("--entry-times", default="09:45:00", help="Comma-separated entry times.")
    options_intraday_sweep.add_argument("--selection-mode", choices=("premium", "delta"), default="delta")
    options_intraday_sweep.add_argument("--min-dte", type=int, default=30)
    options_intraday_sweep.add_argument("--max-dte", type=int, default=45)
    options_intraday_sweep.add_argument("--wing-widths", default="5", help="Comma-separated wing widths.")
    options_intraday_sweep.add_argument("--max-wing-width", type=float, default=20.0)
    options_intraday_sweep.add_argument("--target-deltas", default="0.16", help="Comma-separated target deltas.")
    options_intraday_sweep.add_argument("--target-short-bids", default="1.0", help="Comma-separated premium targets.")
    options_intraday_sweep.add_argument("--max-delta-deviation", type=float, default=0.08)
    options_intraday_sweep.add_argument("--min-credit", type=float, default=0.05)
    options_intraday_sweep.add_argument("--min-credit-ratio", type=float, default=0.10)
    options_intraday_sweep.add_argument("--commission-per-contract", type=float, default=0.65)
    options_intraday_sweep.add_argument("--slippage-per-contract", type=float, default=0.02)
    options_intraday_sweep.add_argument("--exit-decision-time", default="15:55:00")
    options_intraday_sweep.add_argument("--risk-free-rate", type=float, default=0.04)
    options_intraday_sweep.add_argument("--dividend-yield", type=float, default=0.0)
    options_intraday_sweep.add_argument("--profit-targets", default="0.50", help="Comma-separated profit targets.")
    options_intraday_sweep.add_argument("--stop-loss-multiples", default="2.0", help="Comma-separated stop multiples.")
    options_intraday_sweep.add_argument("--exit-dte", type=int, default=21)
    options_intraday_sweep.add_argument(
        "--source",
        choices=("sqlite", "lake"),
        default="sqlite",
        help="Quote backend: sqlite (default) or a Parquet lake.",
    )
    options_intraday_sweep.add_argument("--lake-path", help="Lake root dir/URL when --source lake is used.")
    options_intraday_sweep.add_argument(
        "--fast",
        action="store_true",
        help="FAST screening mode (requires --source lake): materialize only the decision-relevant "
        "bars (open/close + entry + exit-decision times) and near-money strikes via DuckDB. "
        "~100-200x faster; preserves trade structure/verdict but P&L is approximate — confirm "
        "finalists with a full-resolution backtest.",
    )
    options_intraday_sweep.add_argument(
        "--fast-strike-band",
        type=float,
        default=0.15,
        help="Fast mode: keep strikes within this fraction of the underlying (default: 0.15).",
    )
    options_intraday_sweep.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    options_intraday_sweep.set_defaults(func=cmd_options_sweep_intraday_iron_condor)

    short_put = sub.add_parser(
        "options-backtest-short-put",
        help="Run a cash-secured short-put backtest from stored option_quote_bars_1m rows.",
    )
    short_put.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    short_put.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    short_put.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    short_put.add_argument("--entry-time", default="09:45:00", help="Entry time HH:MM:SS (default: 09:45:00).")
    short_put.add_argument("--min-dte", type=int, default=30)
    short_put.add_argument("--max-dte", type=int, default=45)
    short_put.add_argument(
        "--selection-mode",
        choices=("premium", "delta"),
        default="premium",
        help="Short-put selection: premium uses target bid; delta estimates Black-Scholes delta from quotes.",
    )
    short_put.add_argument("--target-short-bid", type=float, default=1.0)
    short_put.add_argument("--target-delta", type=float, default=0.16)
    short_put.add_argument("--max-delta-deviation", type=float, default=0.08)
    short_put.add_argument("--min-credit", type=float, default=0.05)
    short_put.add_argument("--max-bid-ask-spread-pct", type=float, default=1.0)
    short_put.add_argument("--risk-free-rate", type=float, default=0.04)
    short_put.add_argument("--dividend-yield", type=float, default=0.0)
    short_put.add_argument("--profit-target-pct", type=float, default=0.50)
    short_put.add_argument("--stop-loss-credit-multiple", type=float, default=2.0)
    short_put.add_argument("--exit-dte", type=int, default=21)
    short_put.add_argument("--max-concurrent-trades", type=int, default=1)
    short_put.add_argument("--starting-capital", type=float, default=10_000.0, help="Capital base for return metrics.")
    short_put.add_argument(
        "--source",
        choices=("sqlite", "lake"),
        default="sqlite",
        help="Quote backend: sqlite (default) or a Parquet lake.",
    )
    short_put.add_argument("--lake-path", help="Lake root dir/URL when --source lake is used.")
    short_put.add_argument("--output", help="Report path stem. Default prints metrics to stdout.")
    short_put.set_defaults(func=cmd_options_backtest_short_put)

    walkforward = sub.add_parser(
        "options-walkforward-intraday-iron-condor",
        help="Walk-forward (out-of-sample) analysis of the intraday iron-condor sweep.",
    )
    walkforward.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    walkforward.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    walkforward.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    walkforward.add_argument("--train-days", type=int, default=90, help="Calendar days per train fold.")
    walkforward.add_argument("--test-days", type=int, default=30, help="Calendar days per test fold.")
    walkforward.add_argument(
        "--step-days", type=int, default=None, help="Days to advance train start per fold (default: test-days)."
    )
    walkforward.add_argument("--score-key", default="total_pnl", help="In-sample metric to optimize per fold.")
    walkforward.add_argument("--entry-times", default="09:45:00", help="Comma-separated entry times.")
    walkforward.add_argument("--selection-mode", choices=("premium", "delta"), default="delta")
    walkforward.add_argument("--min-dte", type=int, default=30)
    walkforward.add_argument("--max-dte", type=int, default=45)
    walkforward.add_argument("--wing-widths", default="5", help="Comma-separated wing widths.")
    walkforward.add_argument("--target-deltas", default="0.16", help="Comma-separated target deltas.")
    walkforward.add_argument("--target-short-bids", default="1.0", help="Comma-separated premium targets.")
    walkforward.add_argument("--profit-targets", default="0.50", help="Comma-separated profit targets.")
    walkforward.add_argument("--stop-loss-multiples", default="2.0", help="Comma-separated stop multiples.")
    walkforward.add_argument(
        "--source",
        choices=("sqlite", "lake"),
        default="sqlite",
        help="Quote backend: sqlite (default) or a Parquet lake.",
    )
    walkforward.add_argument("--lake-path", help="Lake root dir/URL when --source lake is used.")
    walkforward.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    walkforward.set_defaults(func=cmd_options_walkforward_intraday_iron_condor)

    data_quality = sub.add_parser(
        "options-data-quality-report",
        help="NBBO data-quality report over option_quote_bars_1m (crossed/locked/wide/gaps).",
    )
    data_quality.add_argument("--ticker", default="SPY", help="Underlying ticker (default: SPY).")
    data_quality.add_argument("--start", required=True, help="First trade date YYYY-MM-DD.")
    data_quality.add_argument("--end", required=True, help="Last trade date YYYY-MM-DD.")
    data_quality.add_argument(
        "--max-spread-pct",
        type=float,
        default=0.5,
        help="Flag quotes whose (ask-bid)/mid exceeds this fraction (default 0.5 = 50%%).",
    )
    data_quality.add_argument(
        "--source",
        choices=("sqlite", "lake"),
        default="sqlite",
        help="Quote backend: sqlite (default) or a Parquet lake.",
    )
    data_quality.add_argument("--lake-path", help="Lake root dir/URL when --source lake is used.")
    data_quality.add_argument("--output", help="Markdown report path. Default prints to stdout.")
    data_quality.set_defaults(func=cmd_options_data_quality_report)

    notify_test = sub.add_parser("notify-test", help="Send a test notification through configured alert routes.")
    notify_test.add_argument("--title", default="Trader test", help="Notification title.")
    notify_test.add_argument("--body", default="Notification route works.", help="Notification body.")
    notify_test.add_argument("--error", action="store_true", help="Send as an error/urgent alert.")
    notify_test.set_defaults(func=cmd_notify_test)

    sub.add_parser("schedule", help="Run the daily scheduler (blocks).").set_defaults(func=cmd_schedule)
    sub.add_parser("status", help="Show current state and per-brain equity.").set_defaults(func=cmd_status)
    sub.add_parser("kill", help="Engage kill switch — halts all future runs.").set_defaults(func=cmd_kill)
    sub.add_parser("unkill", help="Clear the kill switch.").set_defaults(func=cmd_unkill)

    seed = sub.add_parser("seed-events", help="Seed deterministic local events for no-key demos.")
    seed.add_argument("--demo", action="store_true", help="Create deterministic demo events.")
    seed.add_argument("--limit", type=int, default=5, help="Maximum demo events to seed.")
    seed.set_defaults(func=cmd_seed_events)

    enrich_status = sub.add_parser("enrichment-status", help="Show Event Enricher V1 status counts.")
    enrich_status.add_argument("--source", help="Only count one source, e.g. demo_news.")
    enrich_status.add_argument("--limit", type=int, default=10_000, help="Maximum events to inspect.")
    enrich_status.set_defaults(func=cmd_enrichment_status)

    enrich = sub.add_parser("enrich-events", help="LLM-enrich stored news_events without trading.")
    enrich.add_argument("--limit", type=int, default=25, help="Maximum events to enrich.")
    enrich.add_argument("--since", help="ISO date/datetime; only enrich events with published_at >= since.")
    enrich.add_argument("--source", help="Only enrich one source, e.g. marketwatch.com.")
    enrich.add_argument("--dry-run", action="store_true", help="Run LLM and validation without persisting results.")
    enrich.add_argument("--mock-llm", action="store_true", help="Use a local deterministic analyst stub; no API key.")
    enrich.set_defaults(func=cmd_enrich_events)

    review = sub.add_parser("review-events", help="Export enriched events for manual markdown review.")
    review.add_argument("--limit", type=int, default=50, help="Maximum events to export.")
    review.add_argument("--source", help="Only export one source.")
    review.add_argument(
        "--only",
        choices=["all", "enriched", "rejected", "missing"],
        default="all",
        help="Filter by Event Enricher V1 status.",
    )
    review.add_argument("--output", required=True, help="Markdown output path under output/reviews/.")
    review.set_defaults(func=cmd_review_events)

    score = sub.add_parser("score-events", help="Score enriched events into research-only candidates.")
    score.add_argument("--source", help="Only score one source, e.g. demo_news.")
    score.add_argument("--limit", type=int, default=100, help="Maximum events to inspect.")
    score.add_argument("--output", default="output/reports/event-candidates.md", help="Markdown output path.")
    score.set_defaults(func=cmd_score_events)

    stage_intents = sub.add_parser(
        "stage-paper-intents",
        help="Convert scored candidates into risk-reviewed paper trade intents. No broker orders.",
    )
    stage_intents.add_argument("--source", help="Only inspect one source, e.g. demo_news.")
    stage_intents.add_argument("--event-type", dest="event_type", help="Only inspect one event_type.")
    stage_intents.add_argument("--min-score", type=float, default=60.0, help="Minimum absolute candidate score.")
    stage_intents.add_argument("--limit", type=int, default=20, help="Maximum events/candidates to inspect.")
    stage_intents.add_argument("--last-price", type=float, required=True, help="Reference price for risk sizing.")
    stage_intents.add_argument("--long-target-pct", type=float, default=0.25, help="Bullish target portfolio weight.")
    stage_intents.add_argument("--short-target-pct", type=float, default=0.0, help="Bearish target weight for now.")
    stage_intents.set_defaults(func=cmd_stage_paper_intents)

    simulate_intents = sub.add_parser(
        "simulate-paper-intents",
        help="Fill approved paper intents through SimBroker only. Refuses live mode.",
    )
    simulate_intents.add_argument("--limit", type=int, default=10, help="Maximum staged intents to simulate.")
    simulate_intents.add_argument("--last-price", type=float, required=True, help="Simulation fill price.")
    simulate_intents.set_defaults(func=cmd_simulate_paper_intents)

    similar = sub.add_parser("similar-events", help="Find point-in-time similar past events for one event.")
    similar.add_argument("--event-id", required=True, help="Stored news_events.event_id to use as the query.")
    similar.add_argument("--as-of", required=True, help="ISO datetime cutoff for point-in-time retrieval.")
    similar.add_argument("--k", type=int, default=10, help="Maximum similar events to return.")
    similar.add_argument(
        "--min-candidates",
        type=int,
        default=30,
        help="Cold-start guard: return no hits unless at least this many candidates are eligible.",
    )
    similar.add_argument("--event-type", help="Only search one event_type.")
    similar.add_argument("--source", help="Only search one source.")
    similar.add_argument("--no-log", action="store_true", help="Do not write event_retrievals rows.")
    similar.add_argument("--output", default="output/reports/similar-events.md", help="Markdown output path.")
    similar.set_defaults(func=cmd_similar_events)

    context = sub.add_parser("candidate-context", help="Attach similar-event context to scored candidates.")
    context.add_argument("--source", help="Only inspect one source, e.g. demo_news.")
    context.add_argument("--as-of", required=True, help="ISO datetime cutoff for point-in-time context.")
    context.add_argument("--event-limit", type=int, default=1000, help="Maximum events to inspect before scoring.")
    context.add_argument("--candidate-limit", type=int, default=10, help="Maximum scored candidates to include.")
    context.add_argument("--hits-per-candidate", type=int, default=3, help="Similar events per candidate.")
    context.add_argument(
        "--min-candidates",
        type=int,
        default=30,
        help="Cold-start guard used for each candidate retrieval.",
    )
    context.add_argument("--no-log", action="store_true", help="Do not write event_retrievals rows.")
    context.add_argument("--output", default="output/reports/candidate-context.md", help="Markdown output path.")
    context.set_defaults(func=cmd_candidate_context)

    from trader.scenarios import SCENARIO_NAMES

    scenario_parser = sub.add_parser(
        "run-scenario",
        help="Run a sample news scenario through ThesisEngine + Aggregator (deterministic demo).",
    )
    scenario_parser.add_argument(
        "scenario",
        choices=SCENARIO_NAMES,
        help="Name of the scenario to run.",
    )
    scenario_parser.add_argument(
        "--output",
        help="Write markdown report to a file. Default: stdout.",
    )
    scenario_parser.set_defaults(func=cmd_run_scenario)

    research = sub.add_parser(
        "research-events",
        help="Event-window study: for each stored Event, compute benchmark forward returns.",
    )
    research.add_argument("--benchmark", default="SPY", help="Ticker to study (default: SPY).")
    research.add_argument("--since", help="ISO date/datetime; filter events with observed_at >= since.")
    research.add_argument("--until", help="ISO date/datetime; filter events with observed_at < until.")
    research.add_argument(
        "--as-of",
        dest="as_of",
        help="ISO datetime cutoff; only include events observed, ingested, and classified by this time.",
    )
    research.add_argument("--source", help="Filter to one source (e.g. 'federalreserve.gov').")
    research.add_argument("--event-type", dest="event_type", help="Filter to one event_type.")
    research.add_argument("--minutes", type=int, default=5, help="Bar size in minutes (default: 5).")
    research.add_argument(
        "--data-provider",
        choices=["yahoo", "alpaca"],
        default="yahoo",
        help="Market data provider for research bars (default: yahoo; alpaca requires keys).",
    )
    research.add_argument("--output", help="Write report to a file (markdown). Default: stdout.")
    research.set_defaults(func=cmd_research_events)

    outcome = sub.add_parser(
        "outcome-backtest",
        help="Yahoo-backed event outcome study for stored normalized events.",
    )
    outcome.add_argument("--benchmark", default="SPY", help="Ticker to study (default: SPY).")
    outcome.add_argument("--since", help="ISO date/datetime; filter events with published_at >= since.")
    outcome.add_argument("--until", help="ISO date/datetime; filter events with published_at < until.")
    outcome.add_argument("--source", help="Filter to one source.")
    outcome.add_argument("--event-type", dest="event_type", help="Filter to one event_type.")
    outcome.add_argument("--limit", type=int, default=10_000, help="Maximum events to inspect.")
    outcome.add_argument(
        "--entry-time",
        choices=["observed_at", "published_at", "classified_at"],
        default="observed_at",
        help="Event timestamp to use as outcome entry time.",
    )
    outcome.add_argument(
        "--group-by",
        action="append",
        help="Group fields; can be repeated and comma-separated.",
    )
    outcome.add_argument("--horizons", help="Comma-separated horizons, e.g. 5m,15m,1h.")
    outcome.add_argument("--minutes", type=int, default=5, help="Yahoo intraday bar size in minutes.")
    outcome.add_argument("--min-sample", type=int, default=10, help="Low-sample warning threshold.")
    outcome.add_argument("--output", default="output/reports/outcomes.md", help="Markdown output path.")
    outcome.set_defaults(func=cmd_outcome_backtest)

    outcome_review = sub.add_parser(
        "outcome-review",
        help="Review an outcome-backtest Markdown report and summarize sample quality.",
    )
    outcome_review.add_argument(
        "--outcome-report",
        default="output/reports/outcomes.md",
        help="Input outcome-backtest Markdown path.",
    )
    outcome_review.add_argument("--output", default="output/reports/outcome-review.md", help="Markdown output path.")
    outcome_review.add_argument(
        "--min-sample",
        type=int,
        default=10,
        help="Minimum sample count for candidate rows.",
    )
    outcome_review.add_argument("--focus-horizon", help="Only review one horizon, e.g. 5m, 15m, 1h, or 1d.")
    outcome_review.set_defaults(func=cmd_outcome_review)

    edge_report = sub.add_parser(
        "edge-report",
        help="Generate a research-only edge validation report from outcome-backtest stats.",
    )
    edge_report.add_argument(
        "--outcome-report",
        default="output/reports/outcomes.md",
        help="Input outcome-backtest Markdown path.",
    )
    edge_report.add_argument("--output", default="output/reports/edge-report.md", help="Markdown output path.")
    edge_report.add_argument("--min-n", type=int, default=30, help="Minimum sample size for candidate edge.")
    edge_report.add_argument(
        "--cost-bps",
        type=float,
        default=2.0,
        help="Round-trip transaction cost assumption in basis points.",
    )
    edge_report.set_defaults(func=cmd_edge_report)

    research_cycle = sub.add_parser(
        "research-cycle",
        help="Run the full research loop: fetch, enrich, score, backtest, review, manifest.",
    )
    research_cycle.add_argument("--mock-llm", action="store_true", help="Use deterministic local enrichment; no API key.")
    research_cycle.add_argument("--skip-fetch", action="store_true", help="Use already stored events.")
    research_cycle.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="Fetch lookback override for supported sources.",
    )
    research_cycle.add_argument("--benchmark", default="SPY", help="Benchmark ticker for outcome study.")
    research_cycle.add_argument("--source", help="Filter stored events to one source.")
    research_cycle.add_argument("--event-type", dest="event_type", help="Filter stored events to one event_type.")
    research_cycle.add_argument("--limit", type=int, default=10_000, help="Maximum stored events to inspect.")
    research_cycle.add_argument("--enrich-limit", type=int, default=100, help="Maximum events to enrich.")
    research_cycle.add_argument("--since", help="ISO datetime lower bound for outcome entry time.")
    research_cycle.add_argument("--until", help="ISO datetime upper bound for outcome entry time.")
    research_cycle.add_argument(
        "--entry-time",
        choices=["observed_at", "published_at", "classified_at"],
        default="observed_at",
        help="Event timestamp to use as outcome entry time.",
    )
    research_cycle.add_argument("--group-by", action="append", help="Outcome group fields; repeatable and comma-separated.")
    research_cycle.add_argument("--horizons", default="5m,15m,30m,1h,4h,1d", help="Outcome horizons.")
    research_cycle.add_argument("--minutes", type=int, default=5, help="Yahoo bar interval.")
    research_cycle.add_argument("--min-sample", type=int, default=10, help="Minimum sample size for review.")
    research_cycle.add_argument("--focus-horizon", help="Only review one horizon.")
    research_cycle.add_argument("--candidate-context", action="store_true", help="Generate point-in-time similar-event context.")
    research_cycle.add_argument("--as-of", help="ISO datetime for candidate-context retrieval. Default now UTC.")
    research_cycle.add_argument("--candidate-limit", type=int, default=10)
    research_cycle.add_argument("--hits-per-candidate", type=int, default=3)
    research_cycle.add_argument("--min-candidates", type=int, default=30)
    research_cycle.add_argument("--reports-dir", default="output/reports", help="Directory for generated reports.")
    research_cycle.set_defaults(func=cmd_research_cycle)

    replay = sub.add_parser(
        "replay",
        help="Replay stored historical prices through deterministic replay-safe brains.",
    )
    replay.add_argument("--ticker", help="Ticker to replay. Defaults to TRADER_TICKER.")
    replay.add_argument("--since", required=True, help="First replay trade date (YYYY-MM-DD).")
    replay.add_argument("--until", required=True, help="Last replay trade date (YYYY-MM-DD).")
    replay.add_argument(
        "--brains",
        default=",".join(REPLAY_SAFE_BRAIN_ORDER),
        help="Comma-separated replay-safe brain names. Defaults to all replay-safe brains.",
    )
    replay.set_defaults(func=cmd_replay)

    data_status = sub.add_parser(
        "data-status",
        help="Report local SQLite data coverage for bars, events, fetches, and research runs.",
    )
    data_status.add_argument("--output", help="Write Markdown to this file instead of stdout.")
    data_status.set_defaults(func=cmd_data_status)

    replay_report = sub.add_parser(
        "replay-report",
        help="Write a historical replay report with train/test and cost diagnostics.",
    )
    replay_report.add_argument("--ticker", help="Ticker to report. Defaults to TRADER_TICKER.")
    replay_report.add_argument("--since", required=True, help="First report trade date (YYYY-MM-DD).")
    replay_report.add_argument("--until", required=True, help="Last report trade date (YYYY-MM-DD).")
    replay_report.add_argument("--train-until", help="Last train-window date; test starts the next calendar day.")
    replay_report.add_argument("--cost-bps", type=float, default=0.0, help="Estimated round-trip/order cost in bps.")
    replay_report.add_argument(
        "--baseline",
        default="BuyAndHoldBrain",
        help="Baseline brain for net comparison.",
    )
    replay_report.add_argument(
        "--min-days",
        type=int,
        default=5,
        help="Hide brains with fewer than N equity days per window.",
    )
    replay_report.add_argument(
        "--output",
        default="output/reports/replay-report.md",
        help="Markdown output path.",
    )
    replay_report.set_defaults(func=cmd_replay_report)

    lb = sub.add_parser(
        "leaderboard",
        help="Rank brains by risk-adjusted equity performance (M5-prep paper-trading horse race).",
    )
    lb.add_argument("--since", help="Earliest trade_date (YYYY-MM-DD).")
    lb.add_argument("--until", help="Latest trade_date (YYYY-MM-DD).")
    lb.add_argument("--output", help="Write Markdown to this file instead of stdout text.")
    lb.add_argument(
        "--baseline",
        default="BuyAndHoldBrain",
        help="Brain to use as the vs-baseline (vs B&H column).",
    )
    lb.add_argument(
        "--min-days",
        type=int,
        default=5,
        help="Hide brains with fewer than N days of equity data (default 5).",
    )
    lb.add_argument(
        "--oos-cutoff",
        dest="oos_cutoff",
        help=(
            "Locked OOS protocol: exclude equity rows on or after this date "
            "(YYYY-MM-DD) from the ranking so the leaderboard only sees "
            "in-sample data. The post-cutoff window is reserved for the "
            "single-variant `leaderboard-oos` command."
        ),
    )
    lb.set_defaults(func=cmd_leaderboard)

    lb_oos = sub.add_parser(
        "leaderboard-oos",
        help=(
            "Score ONE variant against the locked OOS window. "
            "Only path that can ever evaluate a variant on OOS data."
        ),
    )
    lb_oos.add_argument(
        "--variant",
        action="append",
        required=True,
        help=(
            "Single variant/brain name to score on OOS data. Accepts exactly "
            "one value; repeating the flag or passing a comma-separated list "
            "is rejected to enforce the locked-OOS protocol."
        ),
    )
    lb_oos.add_argument(
        "--since",
        required=True,
        help="First OOS trade_date (YYYY-MM-DD), inclusive.",
    )
    lb_oos.set_defaults(func=cmd_leaderboard_oos)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


def cmd_leaderboard(args: argparse.Namespace) -> int:
    """Print or write the horse-race leaderboard."""
    from datetime import date

    from trader.scoring.leaderboard import (
        _filter_curve,
        _parsed_equity_curve,
        build_leaderboard,
    )
    from trader.scoring.metrics import total_return
    from trader.scoring.rendering import (
        BaselineSummary,
        WindowSummary,
        render_markdown_table,
        render_text_table,
    )
    from trader.storage.store import Store

    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise SystemExit(f"Invalid date {value!r}: {exc}") from exc

    since = _parse_date(args.since)
    until = _parse_date(args.until)
    oos_cutoff = _parse_date(getattr(args, "oos_cutoff", None))

    s = get_settings()
    store = Store(s.sqlite_path)

    rows = build_leaderboard(
        store,
        since=since,
        until=until,
        oos_cutoff=oos_cutoff,
        baseline_brain=args.baseline,
    )

    if args.min_days > 0:
        rows = [r for r in rows if r.days >= args.min_days]

    # When oos_cutoff is set, the effective upper bound for the window is the
    # day before the cutoff — keep WindowSummary aligned with what was actually
    # scored so the rendered header doesn't mis-report the OOS exclusion.
    from datetime import timedelta as _timedelta

    effective_until = until
    if oos_cutoff is not None:
        oos_until = oos_cutoff - _timedelta(days=1)
        effective_until = (
            oos_until if effective_until is None else min(effective_until, oos_until)
        )

    if since and effective_until:
        span = (effective_until - since).days + 1
    elif rows:
        span = max(r.days for r in rows)
    else:
        span = 0
    window = WindowSummary(since=since, until=effective_until, days_span=span)

    baseline_raw = _parsed_equity_curve(store, args.baseline)
    baseline_filtered = _filter_curve(
        baseline_raw, since=since, until=effective_until
    )
    if len(baseline_filtered) >= 2:
        baseline_total = total_return(baseline_filtered)
        baseline_days = len(baseline_filtered)
    else:
        baseline_total = None
        baseline_days = len(baseline_filtered)
    baseline_summary = BaselineSummary(
        brain=args.baseline, total_return=baseline_total, days=baseline_days
    )

    if args.output:
        markdown = render_markdown_table(
            rows, window=window, baseline=baseline_summary
        )
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
        print(f"Leaderboard written to {out_path}")
    else:
        print(render_text_table(rows, window=window, baseline=baseline_summary))
    return 0


def cmd_leaderboard_oos(args: argparse.Namespace) -> int:
    """Score ONE variant against the locked OOS window.

    Locked OOS protocol: this CLI command is the ONLY code path in the
    project that scores a variant against the post-cutoff out-of-sample
    window. It deliberately accepts exactly one ``--variant`` — repeating
    the flag or passing a comma-separated list is refused — so the OOS
    window can never be used as a multi-variant horse race (which would
    invalidate the OOS guarantee by re-introducing selection bias). The
    regular ``leaderboard`` command can EXCLUDE OOS data via
    ``--oos-cutoff`` but cannot rank variants on OOS data.
    """
    from datetime import date

    from trader.scoring.leaderboard import build_oos_row

    variants_raw: list[str] = list(args.variant or [])
    if len(variants_raw) != 1:
        print(
            "leaderboard-oos requires exactly one --variant "
            f"(got {len(variants_raw)}). "
            "The locked OOS protocol forbids ranking multiple variants on "
            "the OOS window; run this command once per variant.",
            file=sys.stderr,
        )
        return 2
    variant = variants_raw[0].strip()
    if "," in variant:
        print(
            "leaderboard-oos --variant accepts a single name, not a "
            "comma-separated list. Run the command once per variant.",
            file=sys.stderr,
        )
        return 2
    if not variant:
        print("leaderboard-oos --variant cannot be empty.", file=sys.stderr)
        return 2

    try:
        since = date.fromisoformat(args.since)
    except ValueError as exc:
        raise SystemExit(f"Invalid --since {args.since!r}: {exc}") from exc

    s = get_settings()
    store = Store(s.sqlite_path)
    row = build_oos_row(store, variant=variant, since=since)

    print(f"=== OOS RUN — variant: {variant} ===")
    print(f"  --since: {since.isoformat()}  (OOS window starts here, inclusive)")
    print(
        "  This is the only code path that scores a variant against OOS data."
    )
    print()

    if row.confidence_tier == "insufficient":
        print(
            f"insufficient_oos: only {row.days} day(s) of OOS data for "
            f"{variant}; need at least 5 to compute a meaningful Sharpe."
        )
        return 0

    print(
        f"{'days':>6}  {'TotRet':>9}  {'Ann.Ret':>9}  {'Sharpe':>7}  "
        f"{'MaxDD':>7}  {'Hit%':>5}  {'Trades':>6}  {'Tier':<12}"
    )
    print(
        f"{row.days:>6}  {row.total_return * 100:>+8.2f}%  "
        f"{row.annualized_return * 100:>+8.2f}%  {row.sharpe:>7.2f}  "
        f"{row.max_drawdown * 100:>6.2f}%  {row.hit_rate * 100:>4.0f}%  "
        f"{row.trade_count:>6}  {row.confidence_tier:<12}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
