"""SQLite-backed state store. Single source of truth across brains."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trader.storage.migrations import run_migrations
from trader.storage.utc import ensure_utc, to_iso_z

if TYPE_CHECKING:
    from trader.normalization.models import Event


def _utcnow_iso() -> str:
    return to_iso_z(datetime.now(UTC))


def _parse_datetime_text(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _normalize_news_event_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("published_at", "observed_at", "last_seen_at", "ingested_at", "classified_at"):
        if data.get(key):
            data[key] = to_iso_z(_parse_datetime_text(str(data[key])))
    return data


def _utcnow_iso_precise() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Store:
    """Thin wrapper around sqlite3. Each public method opens its own connection."""

    def __init__(self, db_path: Path, *, bulk_load: bool = False) -> None:
        self.db_path = db_path
        # Opt-in bulk-load tuning for large sequential backfills (--bulk-load).
        # When on, per-day inserts are batched into a single transaction and
        # durability PRAGMAs are relaxed so we don't fsync per row on slow
        # external drives. OFF by default so the normal path is byte-for-byte
        # unchanged.
        self._bulk_load = bulk_load
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        schema_sql = resources.files("trader.storage").joinpath("schema.sql").read_text()
        with self._conn() as c:
            c.executescript(schema_sql)
            run_migrations(c)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self._bulk_load:
            # Keep index pages hot (far fewer random reads on the external SSD)
            # and avoid an fsync per commit. NORMAL is crash-safe under WAL.
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = -524288")  # ~512 MB page cache
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA mmap_size = 268435456")  # 256 MB
        try:
            yield conn
        finally:
            conn.close()

    # ── snapshots ────────────────────────────────────────────────────────────
    def save_snapshot(self, snapshot_id: str, trade_date: str, ticker: str, payload: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO snapshots(snapshot_id, trade_date, ticker, payload_json, created_at) "
                "VALUES (?,?,?,?,?)",
                (snapshot_id, trade_date, ticker, json.dumps(payload, default=str), _utcnow_iso()),
            )

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
            return dict(row) if row else None

    # ── decisions ────────────────────────────────────────────────────────────
    def save_decision(
        self,
        snapshot_id: str,
        brain: str,
        action: str,
        target_pct: float,
        confidence: float | None,
        reasoning: str | None,
        llm_cost_usd: float = 0.0,
    ) -> str:
        decision_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                "INSERT INTO decisions(decision_id, snapshot_id, brain, action, target_pct, "
                "confidence, reasoning, llm_cost_usd, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    snapshot_id,
                    brain,
                    action,
                    target_pct,
                    confidence,
                    reasoning,
                    llm_cost_usd,
                    _utcnow_iso(),
                ),
            )
        return decision_id

    def get_decisions_for_brain(self, brain: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM decisions WHERE brain = ? ORDER BY created_at DESC LIMIT ?",
                (brain, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── orders / fills ───────────────────────────────────────────────────────
    def record_order(
        self,
        client_order_id: str,
        decision_id: str | None,
        brain: str,
        ticker: str,
        side: str,
        qty: float,
        order_type: str,
        limit_price: float | None,
        alpaca_order_id: str | None,
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO orders(client_order_id, decision_id, brain, ticker, "
                "side, qty, order_type, limit_price, submitted_at, alpaca_order_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    client_order_id,
                    decision_id,
                    brain,
                    ticker,
                    side,
                    qty,
                    order_type,
                    limit_price,
                    _utcnow_iso(),
                    alpaca_order_id,
                ),
            )

    def update_order_status(self, client_order_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE orders SET status = ? WHERE client_order_id = ?", (status, client_order_id))

    def record_fill(
        self,
        client_order_id: str,
        filled_qty: float,
        filled_avg_price: float,
        filled_at: datetime | str,
    ) -> str:
        fill_id = str(uuid.uuid4())
        filled_at_dt = _parse_datetime_text(filled_at) if isinstance(filled_at, str) else filled_at
        with self._conn() as c:
            c.execute(
                "INSERT INTO fills(fill_id, client_order_id, filled_qty, filled_avg_price, filled_at, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (fill_id, client_order_id, filled_qty, filled_avg_price, to_iso_z(filled_at_dt), _utcnow_iso()),
            )
        return fill_id

    def count_day_trades_last_n_days(self, brain: str, n_days: int = 5) -> int:
        """How many day trades has this brain done in the trailing n_days.

        A day trade is a round trip (BUY + SELL on the same ticker on the
        same calendar day). Used by `RiskGate` to enforce the PDT rule per
        SEC 15c3-3: brokerages must halt new day trades when a Reg-T
        margin account under $25K hits 3 day-trades in a rolling 5-day
        window.

        Counts by `submitted_at` date in UTC. We don't have execution
        venues' actual fill timestamps in v0; the order submit time is
        a close-enough approximation for paper trading.
        """
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT ticker, substr(submitted_at, 1, 10) AS d, side
                FROM orders
                WHERE brain = ?
                  AND status = 'filled'
                  AND datetime(submitted_at) >= datetime('now', ?)
                """,
                (brain, f"-{n_days} days"),
            ).fetchall()

        # Group by (date, ticker) and check both buy and sell present.
        by_day_ticker: dict[tuple[str, str], set[str]] = {}
        for r in rows:
            key = (r["d"], r["ticker"])
            by_day_ticker.setdefault(key, set()).add(r["side"])
        return sum(1 for sides in by_day_ticker.values() if "buy" in sides and "sell" in sides)

    # ── per-brain virtual portfolio ─────────────────────────────────────────
    def get_or_init_portfolio(self, brain: str, starting_cash: float) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM brain_portfolios WHERE brain = ?", (brain,)).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO brain_portfolios(brain, cash, updated_at) VALUES (?,?,?)",
                    (brain, starting_cash, _utcnow_iso()),
                )
                row = c.execute("SELECT * FROM brain_portfolios WHERE brain = ?", (brain,)).fetchone()
            return dict(row)

    def update_portfolio(
        self,
        brain: str,
        cash: float,
        position_qty: float,
        avg_cost: float,
        realized_pnl: float,
    ) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE brain_portfolios SET cash=?, position_qty=?, avg_cost=?, realized_pnl=?, "
                "updated_at=? WHERE brain=?",
                (cash, position_qty, avg_cost, realized_pnl, _utcnow_iso(), brain),
            )

    def record_equity(self, brain: str, trade_date: str, equity: float) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO brain_equity_curve(brain, trade_date, equity) VALUES (?,?,?)",
                (brain, trade_date, equity),
            )

    def get_equity_curve(self, brain: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT trade_date, equity FROM brain_equity_curve WHERE brain=? ORDER BY trade_date",
                (brain,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_equity(self, brain: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT trade_date, equity FROM brain_equity_curve WHERE brain=? ORDER BY trade_date DESC LIMIT 1",
                (brain,),
            ).fetchone()
            return dict(row) if row else None

    def list_brains(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT brain FROM brain_portfolios").fetchall()
            return [r["brain"] for r in rows]

    # ── historical daily bars ──────────────────────────────────────────────
    def upsert_historical_bars(self, ticker: str, rows: list[dict[str, Any]]) -> int:
        """Idempotent multi-row upsert for replay OHLCV + macro rows.

        Row keys: trade_date, open, high, low, close, volume, vix_close,
        yield_curve_10y_2y. Returns the number of rows persisted.
        """
        if not rows:
            return 0
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO historical_bars(
                    ticker, trade_date, open, high, low, close, volume,
                    vix_close, yield_curve_10y_2y
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker, trade_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    vix_close = COALESCE(excluded.vix_close, historical_bars.vix_close),
                    yield_curve_10y_2y = COALESCE(
                        excluded.yield_curve_10y_2y,
                        historical_bars.yield_curve_10y_2y
                    )
                """,
                [
                    (
                        ticker,
                        row["trade_date"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row.get("volume", 0),
                        row.get("vix_close"),
                        row.get("yield_curve_10y_2y"),
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def get_historical_bars(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return historical bars sorted ascending by trade_date."""
        clauses = ["ticker = ?"]
        params: list[Any] = [ticker]
        if since is not None:
            clauses.append("trade_date >= ?")
            params.append(since)
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)

        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM historical_bars
                WHERE {" AND ".join(clauses)}
                ORDER BY trade_date ASC
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    # ── options research lab ───────────────────────────────────────────────
    def upsert_option_chain_eod(self, ticker: str, rows: list[Any]) -> int:
        """Idempotent upsert for normalized EOD option-chain rows."""
        if not rows:
            return 0
        symbol = ticker.strip().upper()
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO option_chain_eod(
                    ticker, trade_date, expiration, strike, call_put, bid, ask,
                    implied_vol, delta, gamma, theta, vega, rho
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker, trade_date, expiration, strike, call_put) DO UPDATE SET
                    bid = excluded.bid,
                    ask = excluded.ask,
                    implied_vol = excluded.implied_vol,
                    delta = excluded.delta,
                    gamma = excluded.gamma,
                    theta = excluded.theta,
                    vega = excluded.vega,
                    rho = excluded.rho
                """,
                [
                    (
                        symbol,
                        row.trade_date.isoformat(),
                        row.expiration.isoformat(),
                        float(row.strike),
                        row.call_put,
                        row.bid,
                        row.ask,
                        row.implied_vol,
                        row.delta,
                        row.gamma,
                        row.theta,
                        row.vega,
                        row.rho,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def get_option_chain_eod(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
        trade_date: str | None = None,
    ) -> list[Any]:
        """Return normalized option-chain rows sorted by date/contract."""
        from datetime import date

        from trader.options.models import OptionQuote

        clauses = ["ticker = ?"]
        params: list[Any] = [ticker.strip().upper()]
        if trade_date is not None:
            clauses.append("trade_date = ?")
            params.append(trade_date)
        if since is not None:
            clauses.append("trade_date >= ?")
            params.append(since)
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)

        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM option_chain_eod
                WHERE {" AND ".join(clauses)}
                ORDER BY trade_date ASC, expiration ASC, strike ASC, call_put ASC
                """,
                params,
            ).fetchall()
        return [
            OptionQuote(
                trade_date=date.fromisoformat(row["trade_date"]),
                ticker=row["ticker"],
                expiration=date.fromisoformat(row["expiration"]),
                strike=float(row["strike"]),
                call_put=row["call_put"],
                bid=row["bid"],
                ask=row["ask"],
                implied_vol=row["implied_vol"],
                delta=row["delta"],
                gamma=row["gamma"],
                theta=row["theta"],
                vega=row["vega"],
                rho=row["rho"],
            )
            for row in rows
        ]

    def upsert_option_volatility_history(self, ticker: str, rows: list[Any]) -> int:
        """Idempotent upsert for DoltHub volatility_history rows."""
        if not rows:
            return 0
        symbol = ticker.strip().upper()
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO option_volatility_history(
                    ticker, trade_date, hv_current, hv_week_ago, hv_month_ago,
                    hv_year_high, hv_year_low, iv_current, iv_week_ago,
                    iv_month_ago, iv_year_high, iv_year_low
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker, trade_date) DO UPDATE SET
                    hv_current = excluded.hv_current,
                    hv_week_ago = excluded.hv_week_ago,
                    hv_month_ago = excluded.hv_month_ago,
                    hv_year_high = excluded.hv_year_high,
                    hv_year_low = excluded.hv_year_low,
                    iv_current = excluded.iv_current,
                    iv_week_ago = excluded.iv_week_ago,
                    iv_month_ago = excluded.iv_month_ago,
                    iv_year_high = excluded.iv_year_high,
                    iv_year_low = excluded.iv_year_low
                """,
                [
                    (
                        symbol,
                        row.trade_date.isoformat(),
                        row.hv_current,
                        row.hv_week_ago,
                        row.hv_month_ago,
                        row.hv_year_high,
                        row.hv_year_low,
                        row.iv_current,
                        row.iv_week_ago,
                        row.iv_month_ago,
                        row.iv_year_high,
                        row.iv_year_low,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def get_option_volatility_history(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[Any]:
        """Return normalized volatility-history rows sorted by trade_date."""
        from datetime import date

        from trader.options.models import VolatilityHistoryRow

        clauses = ["ticker = ?"]
        params: list[Any] = [ticker.strip().upper()]
        if since is not None:
            clauses.append("trade_date >= ?")
            params.append(since)
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)

        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM option_volatility_history
                WHERE {" AND ".join(clauses)}
                ORDER BY trade_date ASC
                """,
                params,
            ).fetchall()
        return [
            VolatilityHistoryRow(
                trade_date=date.fromisoformat(row["trade_date"]),
                ticker=row["ticker"],
                hv_current=row["hv_current"],
                hv_week_ago=row["hv_week_ago"],
                hv_month_ago=row["hv_month_ago"],
                hv_year_high=row["hv_year_high"],
                hv_year_low=row["hv_year_low"],
                iv_current=row["iv_current"],
                iv_week_ago=row["iv_week_ago"],
                iv_month_ago=row["iv_month_ago"],
                iv_year_high=row["iv_year_high"],
                iv_year_low=row["iv_year_low"],
            )
            for row in rows
        ]

    def upsert_option_quote_bars_1m(self, ticker: str, rows: list[Any]) -> int:
        """Idempotent upsert for provider-neutral 1-minute option NBBO quote bars."""
        if not rows:
            return 0
        symbol = ticker.strip().upper()
        with self._conn() as c:
            # In bulk-load mode, wrap the whole day's rows in ONE explicit
            # transaction. Without this, the autocommit connection fsyncs once
            # per row — the dominant cost of a large backfill on an external SSD.
            if self._bulk_load:
                c.execute("BEGIN")
            c.executemany(
                """
                INSERT INTO option_quote_bars_1m(
                    ticker, quote_ts, trade_date, expiration, strike, call_put, bid, ask,
                    underlying_price, bid_size, ask_size, bid_exchange, ask_exchange, bid_condition,
                    ask_condition, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker, quote_ts, expiration, strike, call_put) DO UPDATE SET
                    bid = excluded.bid,
                    ask = excluded.ask,
                    underlying_price = excluded.underlying_price,
                    bid_size = excluded.bid_size,
                    ask_size = excluded.ask_size,
                    bid_exchange = excluded.bid_exchange,
                    ask_exchange = excluded.ask_exchange,
                    bid_condition = excluded.bid_condition,
                    ask_condition = excluded.ask_condition,
                    source = excluded.source
                """,
                [
                    (
                        symbol,
                        row.timestamp.isoformat(),
                        row.trade_date.isoformat(),
                        row.expiration.isoformat(),
                        float(row.strike),
                        row.call_put,
                        row.bid,
                        row.ask,
                        row.underlying_price,
                        row.bid_size,
                        row.ask_size,
                        row.bid_exchange,
                        row.ask_exchange,
                        row.bid_condition,
                        row.ask_condition,
                        row.source,
                    )
                    for row in rows
                ],
            )
            if self._bulk_load:
                c.execute("COMMIT")
        return len(rows)

    def get_option_quote_bars_1m(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
        trade_date: str | None = None,
        expiration: str | None = None,
    ) -> list[Any]:
        """Return 1-minute option quote bars sorted by timestamp/contract."""
        from datetime import date, datetime

        from trader.options.models import OptionQuoteBar

        clauses = ["ticker = ?"]
        params: list[Any] = [ticker.strip().upper()]
        if trade_date is not None:
            clauses.append("trade_date = ?")
            params.append(trade_date)
        if since is not None:
            clauses.append("trade_date >= ?")
            params.append(since)
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)
        if expiration is not None:
            clauses.append("expiration = ?")
            params.append(expiration)

        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT *
                FROM option_quote_bars_1m
                WHERE {" AND ".join(clauses)}
                ORDER BY quote_ts ASC, expiration ASC, strike ASC, call_put ASC
                """,
                params,
            ).fetchall()
        return [
            OptionQuoteBar(
                timestamp=datetime.fromisoformat(row["quote_ts"]),
                ticker=row["ticker"],
                expiration=date.fromisoformat(row["expiration"]),
                strike=float(row["strike"]),
                call_put=row["call_put"],
                bid=row["bid"],
                ask=row["ask"],
                underlying_price=row["underlying_price"],
                bid_size=row["bid_size"],
                ask_size=row["ask_size"],
                bid_exchange=row["bid_exchange"],
                ask_exchange=row["ask_exchange"],
                bid_condition=row["bid_condition"],
                ask_condition=row["ask_condition"],
                source=row["source"],
            )
            for row in rows
        ]

    def upsert_backfill_ledger(
        self,
        ticker: str,
        trade_date: str,
        *,
        status: str,
        expirations_pulled: int = 0,
        quote_rows: int = 0,
        attempts: int = 0,
        last_error: str | None = None,
    ) -> None:
        """Record per-(ticker, trade_date) backfill outcome for resumable pulls."""
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO option_quote_backfill_ledger(
                    ticker, trade_date, status, expirations_pulled, quote_rows, attempts, last_error, updated_at
                ) VALUES (?,?,?,?,?,?,?, datetime('now'))
                ON CONFLICT(ticker, trade_date) DO UPDATE SET
                    status = excluded.status,
                    expirations_pulled = excluded.expirations_pulled,
                    quote_rows = excluded.quote_rows,
                    attempts = excluded.attempts,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (ticker.strip().upper(), trade_date, status, expirations_pulled, quote_rows, attempts, last_error),
            )

    def get_backfill_done_dates(self, ticker: str, *, statuses: tuple[str, ...] = ("done", "empty")) -> set[str]:
        """Return trade_dates already completed (for resume), by status."""
        if not statuses:
            return set()
        placeholders = ",".join("?" for _ in statuses)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT trade_date FROM option_quote_backfill_ledger WHERE ticker = ? AND status IN ({placeholders})",
                (ticker.strip().upper(), *statuses),
            ).fetchall()
        return {row["trade_date"] for row in rows}

    def get_backfill_ledger(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return ledger rows for a ticker, optionally bounded by trade_date."""
        clauses = ["ticker = ?"]
        params: list[Any] = [ticker.strip().upper()]
        if since is not None:
            clauses.append("trade_date >= ?")
            params.append(since)
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM option_quote_backfill_ledger WHERE {' AND '.join(clauses)} ORDER BY trade_date ASC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def intraday_quote_coverage(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Per-trade-date row/expiration counts (SQL aggregates, not full rows)."""
        clauses = ["ticker = ?"]
        params: list[Any] = [ticker.strip().upper()]
        if since is not None:
            clauses.append("trade_date >= ?")
            params.append(since)
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)
        where = " AND ".join(clauses)
        with self._conn() as c:
            by_date = c.execute(
                f"""
                SELECT trade_date, COUNT(*) AS rows, COUNT(DISTINCT expiration) AS expirations
                FROM option_quote_bars_1m
                WHERE {where}
                GROUP BY trade_date
                ORDER BY trade_date ASC
                """,
                params,
            ).fetchall()
            missing_spot = c.execute(
                f"SELECT COUNT(*) FROM option_quote_bars_1m WHERE {where} AND underlying_price IS NULL",
                params,
            ).fetchone()[0]
        return {"by_date": [dict(row) for row in by_date], "rows_missing_spot": int(missing_spot)}

    def save_iron_condor_backtest_result(self, result: Any) -> None:
        """Persist a research-only iron-condor backtest result and child rows."""
        with self._conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO iron_condor_backtest_runs(
                    run_id, ticker, start_date, end_date, params_json, summary_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    result.run_id,
                    result.config.ticker,
                    result.config.start.isoformat() if result.config.start else None,
                    result.config.end.isoformat() if result.config.end else None,
                    json.dumps(
                        {
                            "profit_target_pct": result.config.profit_target_pct,
                            "stop_loss_credit_multiple": result.config.stop_loss_credit_multiple,
                            "exit_dte": result.config.exit_dte,
                            "max_concurrent_trades": result.config.max_concurrent_trades,
                            "selector": {
                                "min_dte": result.config.selector.min_dte,
                                "max_dte": result.config.selector.max_dte,
                                "target_delta": result.config.selector.target_delta,
                                "wing_width": result.config.selector.wing_width,
                                "min_credit": result.config.selector.min_credit,
                            },
                        }
                    ),
                    json.dumps(result.summary.__dict__),
                ),
            )
            c.execute("DELETE FROM iron_condor_trades WHERE run_id = ?", (result.run_id,))
            c.execute("DELETE FROM iron_condor_daily_marks WHERE run_id = ?", (result.run_id,))
            c.executemany(
                """
                INSERT INTO iron_condor_trades(
                    trade_id, run_id, ticker, entry_date, exit_date, expiration,
                    short_put_strike, long_put_strike, short_call_strike, long_call_strike,
                    entry_credit, exit_debit, max_risk, pnl, exit_reason,
                    holding_days, dte_entry, dte_exit
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        trade.trade_id,
                        result.run_id,
                        trade.ticker,
                        trade.entry_date.isoformat(),
                        trade.exit_date.isoformat() if trade.exit_date else None,
                        trade.expiration.isoformat(),
                        trade.short_put_strike,
                        trade.long_put_strike,
                        trade.short_call_strike,
                        trade.long_call_strike,
                        trade.entry_credit,
                        trade.exit_debit,
                        trade.max_risk,
                        trade.pnl,
                        trade.exit_reason,
                        trade.holding_days,
                        trade.dte_entry,
                        trade.dte_exit,
                    )
                    for trade in result.trades
                ],
            )
            c.executemany(
                """
                INSERT INTO iron_condor_daily_marks(run_id, trade_id, mark_date, exit_debit, pnl, dte)
                VALUES (?,?,?,?,?,?)
                """,
                [
                    (
                        result.run_id,
                        mark.trade_id,
                        mark.mark_date.isoformat(),
                        mark.exit_debit,
                        mark.pnl,
                        mark.dte,
                    )
                    for mark in result.marks
                ],
            )

    def save_intraday_iron_condor_backtest_result(self, result: Any) -> None:
        """Persist an intraday iron-condor backtest result and child rows."""
        with self._conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO iron_condor_intraday_backtest_runs(
                    run_id, ticker, start_date, end_date, entry_time, params_json, summary_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    result.run_id,
                    result.config.ticker,
                    result.config.start.isoformat() if result.config.start else None,
                    result.config.end.isoformat() if result.config.end else None,
                    result.config.entry_time,
                    json.dumps(
                        {
                            "profit_target_pct": result.config.profit_target_pct,
                            "stop_loss_credit_multiple": result.config.stop_loss_credit_multiple,
                            "exit_dte": result.config.exit_dte,
                            "max_concurrent_trades": result.config.max_concurrent_trades,
                            "selector": result.config.selector.__dict__,
                        }
                    ),
                    json.dumps(result.summary.__dict__),
                ),
            )
            c.execute("DELETE FROM iron_condor_intraday_trades WHERE run_id = ?", (result.run_id,))
            c.execute("DELETE FROM iron_condor_intraday_marks WHERE run_id = ?", (result.run_id,))
            c.executemany(
                """
                INSERT INTO iron_condor_intraday_trades(
                    trade_id, run_id, ticker, entry_ts, exit_ts, expiration,
                    short_put_strike, long_put_strike, short_call_strike, long_call_strike,
                    entry_credit, exit_debit, max_risk, pnl, exit_reason,
                    holding_minutes, dte_entry, dte_exit, short_put_delta, short_call_delta,
                    max_favorable_pnl, max_adverse_pnl, mark_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        trade.trade_id,
                        result.run_id,
                        trade.ticker,
                        trade.entry_ts.isoformat(),
                        trade.exit_ts.isoformat() if trade.exit_ts else None,
                        trade.expiration.isoformat(),
                        trade.short_put_strike,
                        trade.long_put_strike,
                        trade.short_call_strike,
                        trade.long_call_strike,
                        trade.entry_credit,
                        trade.exit_debit,
                        trade.max_risk,
                        trade.pnl,
                        trade.exit_reason,
                        trade.holding_minutes,
                        trade.dte_entry,
                        trade.dte_exit,
                        trade.short_put_delta,
                        trade.short_call_delta,
                        trade.max_favorable_pnl,
                        trade.max_adverse_pnl,
                        trade.mark_count,
                    )
                    for trade in result.trades
                ],
            )
            c.executemany(
                """
                INSERT INTO iron_condor_intraday_marks(
                    run_id, trade_id, mark_ts, exit_debit, pnl, dte
                ) VALUES (?,?,?,?,?,?)
                """,
                [
                    (
                        result.run_id,
                        mark.trade_id,
                        mark.mark_ts.isoformat(),
                        mark.exit_debit,
                        mark.pnl,
                        mark.dte,
                    )
                    for mark in result.marks
                ],
            )

    # ── LLM calls ────────────────────────────────────────────────────────────
    def record_llm_call(
        self,
        decision_id: str | None,
        brain: str,
        model: str,
        prompt_hash: str,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_tokens: int,
        cost_usd: float | None,
        latency_ms: int | None,
    ) -> str:
        call_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                "INSERT INTO llm_calls(call_id, decision_id, brain, model, prompt_hash, "
                "input_tokens, output_tokens, cached_tokens, cost_usd, latency_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    call_id,
                    decision_id,
                    brain,
                    model,
                    prompt_hash,
                    input_tokens,
                    output_tokens,
                    cached_tokens,
                    cost_usd,
                    latency_ms,
                    _utcnow_iso(),
                ),
            )
        return call_id

    def llm_cost_today(self) -> float:
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(cost_usd),0) AS total FROM llm_calls WHERE substr(created_at,1,10) = date('now')"
            ).fetchone()
            return float(row["total"])

    # ── system event log (kill switch, brain errors, etc.) ─────────────────
    def record_event(self, level: str, source: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO events(event_id, level, source, message, payload_json, created_at) VALUES (?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    level,
                    source,
                    message,
                    json.dumps(payload) if payload else None,
                    _utcnow_iso(),
                ),
            )

    # ── normalized news/filing events (per brain/08) ───────────────────────
    def save_news_event(self, event: Event) -> None:
        """Upsert a normalized Event while preserving first-seen timing."""
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO news_events(
                    event_id, source, source_url, title, summary,
                    published_at, observed_at, last_seen_at, ingested_at, classified_at,
                    event_type, sentiment, sentiment_score, urgency,
                    novelty_score, source_credibility,
                    entities_json, asset_scope_json, index_exposure_json,
                    evidence_json, model_outputs_json, raw_artifact_path
                ) VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?, ?,?,?, ?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET
                    source = excluded.source,
                    source_url = excluded.source_url,
                    title = excluded.title,
                    summary = excluded.summary,
                    published_at = excluded.published_at,
                    -- last_seen_at is monotonic: only moves forward. An
                    -- enrichment update path reconstructs Event from
                    -- storage with the original observed_at, so without
                    -- this guard a later enrichment would *regress*
                    -- last_seen_at back to the first sighting. Per
                    -- Codex re-review (2026-05-20).
                    last_seen_at = CASE
                        WHEN news_events.last_seen_at IS NULL THEN excluded.last_seen_at
                        WHEN excluded.last_seen_at > news_events.last_seen_at THEN excluded.last_seen_at
                        ELSE news_events.last_seen_at
                    END,
                    classified_at = excluded.classified_at,
                    event_type = excluded.event_type,
                    sentiment = excluded.sentiment,
                    sentiment_score = excluded.sentiment_score,
                    urgency = excluded.urgency,
                    novelty_score = excluded.novelty_score,
                    source_credibility = excluded.source_credibility,
                    entities_json = excluded.entities_json,
                    asset_scope_json = excluded.asset_scope_json,
                    index_exposure_json = excluded.index_exposure_json,
                    evidence_json = excluded.evidence_json,
                    model_outputs_json = excluded.model_outputs_json,
                    raw_artifact_path = excluded.raw_artifact_path
                """,
                (
                    event.event_id,
                    event.source,
                    event.source_url,
                    event.title,
                    event.summary,
                    to_iso_z(event.published_at),
                    to_iso_z(event.observed_at),
                    to_iso_z(event.observed_at),
                    to_iso_z(event.ingested_at),
                    to_iso_z(event.classified_at) if event.classified_at else None,
                    event.event_type,
                    event.sentiment,
                    event.sentiment_score,
                    event.urgency,
                    event.novelty_score,
                    event.source_credibility,
                    json.dumps([e.model_dump(mode="json") for e in event.entities]),
                    json.dumps(list(event.asset_scope)),
                    json.dumps(list(event.index_exposure)),
                    json.dumps([e.model_dump(mode="json") for e in event.evidence]),
                    json.dumps([m.model_dump(mode="json") for m in event.model_outputs]),
                    event.raw_artifact_path,
                ),
            )

    def get_news_events(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        as_of: datetime | None = None,
        source: str | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return raw row dicts (JSON columns stay strings).

        `since`/`until` apply to `observed_at`. When provided, `as_of` limits
        visibility to events observed, ingested, and classified by that time.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("datetime(observed_at) >= datetime(?)")
            params.append(to_iso_z(since))
        if until is not None:
            clauses.append("datetime(observed_at) < datetime(?)")
            params.append(to_iso_z(until))
        if as_of is not None:
            clauses.extend(
                [
                    "datetime(observed_at) <= datetime(?)",
                    "datetime(ingested_at) <= datetime(?)",
                    "classified_at IS NOT NULL",
                    "datetime(classified_at) <= datetime(?)",
                ]
            )
            as_of_text = to_iso_z(as_of)
            params.extend([as_of_text, as_of_text, as_of_text])
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM news_events {where} "
                "ORDER BY datetime(observed_at), datetime(published_at), event_id LIMIT ?",
                params,
            ).fetchall()
            return [_normalize_news_event_row(r) for r in rows]

    def count_breaking_events_since(self, since: datetime, until: datetime | None = None) -> int:
        """How many breaking-urgency events landed since `since` (UTC).

        Used by `HybridBrain`'s tier-1 short-circuit per
        `brain/20_llm_decision_boundary_adr.md`: the LLM is skipped when the
        classical signal is confident AND no breaking news has arrived
        recently. Counts by `observed_at`, not `published_at`, so a back-dated
        publish does not bypass the gate.
        """
        sql = "SELECT COUNT(*) AS n FROM news_events WHERE urgency = 'breaking' AND datetime(observed_at) >= datetime(?)"
        params: list[Any] = [to_iso_z(since)]
        if until is not None:
            sql += " AND datetime(observed_at) <= datetime(?)"
            params.append(to_iso_z(until))
        with self._conn() as c:
            row = c.execute(sql, params).fetchone()
            return int(row["n"])

    def count_news_events(self, *, source: str | None = None) -> int:
        with self._conn() as c:
            if source:
                row = c.execute("SELECT COUNT(*) AS n FROM news_events WHERE source = ?", (source,)).fetchone()
            else:
                row = c.execute("SELECT COUNT(*) AS n FROM news_events").fetchone()
            return int(row["n"])

    # ── source fetch quality ledger ────────────────────────────────────────
    def start_source_fetch(self, source: str, *, lookback_days: int | None) -> str:
        fetch_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO source_fetches(fetch_id, source, attempted_at, status, lookback_days)
                VALUES (?,?,?,?,?)
                """,
                (fetch_id, source, _utcnow_iso_precise(), "running", lookback_days),
            )
        return fetch_id

    def finish_source_fetch(
        self,
        fetch_id: str,
        *,
        status: str,
        item_count: int,
        persisted_count: int,
        latency_ms: int | None,
        error: str = "",
    ) -> None:
        if status not in {"ok", "empty", "error"}:
            raise ValueError(f"Unsupported source fetch status: {status}")
        with self._conn() as c:
            c.execute(
                """
                UPDATE source_fetches
                SET finished_at=?, status=?, item_count=?, persisted_count=?, latency_ms=?, error=?
                WHERE fetch_id=?
                """,
                (
                    _utcnow_iso_precise(),
                    status,
                    int(item_count),
                    int(persisted_count),
                    latency_ms,
                    error,
                    fetch_id,
                ),
            )

    def list_source_fetches(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM source_fetches
                ORDER BY attempted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def source_fetch_summary(self, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.list_source_fetches(limit=limit)
        summary: dict[str, dict[str, Any]] = {}
        for row in rows:
            source = str(row["source"])
            current = summary.setdefault(
                source,
                {
                    "source": source,
                    "latest_fetch_id": row["fetch_id"],
                    "latest_attempted_at": row["attempted_at"],
                    "latest_finished_at": row["finished_at"],
                    "latest_status": row["status"],
                    "latest_item_count": row["item_count"],
                    "latest_persisted_count": row["persisted_count"],
                    "latest_latency_ms": row["latency_ms"],
                    "latest_error": row["error"],
                    "attempt_count": 0,
                    "ok_count": 0,
                    "empty_count": 0,
                    "error_count": 0,
                },
            )
            current["attempt_count"] += 1
            status = str(row["status"])
            if status == "ok":
                current["ok_count"] += 1
            elif status == "empty":
                current["empty_count"] += 1
            elif status == "error":
                current["error_count"] += 1

        return sorted(summary.values(), key=lambda item: str(item["source"]))

    # ── research cycle audit runs ──────────────────────────────────────────
    def create_research_run(
        self,
        *,
        command: dict[str, Any],
        benchmark: str,
        entry_time: str,
        horizons: str,
        group_by: str,
        since: str | None,
        until: str | None,
        data_provider: str,
        events_before: int,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO research_runs(
                    run_id, started_at, status, command_json, benchmark, entry_time,
                    horizons, group_by, since, until, data_provider, events_before
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    _utcnow_iso(),
                    "running",
                    json.dumps(command, default=str),
                    benchmark,
                    entry_time,
                    horizons,
                    group_by,
                    since,
                    until,
                    data_provider,
                    events_before,
                ),
            )
        return run_id

    def finish_research_run(
        self,
        run_id: str,
        *,
        status: str,
        events_after: int,
        enriched_count: int,
        rejected_count: int,
        candidate_count: int,
        outcome_report_path: str,
        review_report_path: str,
        manifest_path: str,
        error: str = "",
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError(f"Unsupported research run status: {status}")
        with self._conn() as c:
            c.execute(
                """
                UPDATE research_runs
                SET finished_at=?, status=?, events_after=?, enriched_count=?, rejected_count=?,
                    candidate_count=?, outcome_report_path=?, review_report_path=?,
                    manifest_path=?, error=?
                WHERE run_id=?
                """,
                (
                    _utcnow_iso(),
                    status,
                    events_after,
                    enriched_count,
                    rejected_count,
                    candidate_count,
                    outcome_report_path,
                    review_report_path,
                    manifest_path,
                    error,
                    run_id,
                ),
            )

    def list_research_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM research_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_research_run_artifact(
        self,
        run_id: str,
        *,
        artifact_type: str,
        path: str,
        sha256: str = "",
    ) -> str:
        artifact_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO research_run_artifacts(artifact_id, run_id, artifact_type, path, sha256)
                VALUES (?,?,?,?,?)
                """,
                (artifact_id, run_id, artifact_type, path, sha256),
            )
        return artifact_id

    def list_research_run_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM research_run_artifacts
                WHERE run_id = ?
                ORDER BY created_at, artifact_type
                """,
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ── paper trade intents ────────────────────────────────────────────────
    def save_paper_trade_intent(self, intent) -> None:
        created_at = intent.created_at.isoformat() if hasattr(intent.created_at, "isoformat") else str(intent.created_at)
        with self._conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO paper_trade_intents(
                    intent_id, event_id, created_at, ticker, direction, candidate_score,
                    confidence, proposed_action, proposed_target_pct, risk_status,
                    risk_reason, final_action, final_qty, simulated_order_id, status,
                    source, event_type, title
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    intent.intent_id,
                    intent.event_id,
                    created_at,
                    intent.ticker,
                    intent.direction,
                    intent.candidate_score,
                    intent.confidence,
                    intent.proposed_action,
                    intent.proposed_target_pct,
                    intent.risk_status,
                    intent.risk_reason,
                    intent.final_action,
                    intent.final_qty,
                    intent.simulated_order_id,
                    intent.status,
                    intent.source,
                    intent.event_type,
                    intent.title,
                ),
            )

    def list_paper_trade_intents(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM paper_trade_intents
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_paper_trade_intent_status(
        self,
        intent_id: str,
        status: str,
        *,
        simulated_order_id: str = "",
    ) -> None:
        if status not in {"staged", "risk_blocked", "simulated", "skipped"}:
            raise ValueError(f"Unsupported paper trade intent status: {status}")
        with self._conn() as c:
            c.execute(
                """
                UPDATE paper_trade_intents
                SET status=?, simulated_order_id=?
                WHERE intent_id=?
                """,
                (status, simulated_order_id, intent_id),
            )

    def get_news_event_parsed(self, event_id: str) -> Event | None:
        """Return one parsed Event by id."""
        from trader.normalization.models import event_from_row

        with self._conn() as c:
            row = c.execute("SELECT * FROM news_events WHERE event_id = ?", (event_id,)).fetchone()
            return event_from_row(dict(row)) if row else None

    def get_news_events_parsed(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        as_of: datetime | None = None,
        source: str | None = None,
        event_type: str | None = None,
        limit: int = 10_000,
    ) -> list[Event]:
        """Same as get_news_events() but returns parsed Event objects."""
        from trader.normalization.models import event_from_row

        return [
            event_from_row(r)
            for r in self.get_news_events(
                since=since,
                until=until,
                as_of=as_of,
                source=source,
                event_type=event_type,
                limit=limit,
            )
        ]

    def get_events_needing_enrichment(
        self,
        *,
        classifier: str,
        prompt_version: str,
        since: datetime | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Return parsed events lacking a successful enrichment output."""
        candidates = self.get_news_events_parsed(since=since, source=source, limit=limit * 5)
        out: list[Event] = []
        for event in candidates:
            has_version = any(
                meta.classifier == classifier
                and meta.prompt_version == prompt_version
                and meta.validation_status in {"auto_passed", "human_reviewed"}
                for meta in event.model_outputs
            )
            if not has_version:
                out.append(event)
            if len(out) >= limit:
                break
        return out

    def update_news_event_enrichment(self, event: Event) -> None:
        """Persist an enriched Event row by replacing the existing row."""
        self.save_news_event(event)

    # ── event retrieval sidecar ─────────────────────────────────────────────
    def record_event_retrieval(self, event_id: str, *, retrieved_at: datetime, query_hash: str) -> str:
        retrieval_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute(
                "INSERT INTO event_retrievals(retrieval_id, event_id, retrieved_at, query_hash) VALUES (?,?,?,?)",
                (retrieval_id, event_id, to_iso_z(retrieved_at), query_hash),
            )
        return retrieval_id

    def latest_event_retrievals_before(self, event_ids: list[str], *, before: datetime) -> dict[str, datetime]:
        if not event_ids:
            return {}
        placeholders = ",".join("?" for _ in event_ids)
        params: list[Any] = [*event_ids, to_iso_z(before)]
        with self._conn() as c:
            rows = c.execute(
                f"""
                SELECT event_id, retrieved_at
                FROM event_retrievals
                WHERE event_id IN ({placeholders}) AND datetime(retrieved_at) < datetime(?)
                ORDER BY datetime(retrieved_at) DESC
                """,
                params,
            ).fetchall()
        latest: dict[str, datetime] = {}
        for row in rows:
            event_id = str(row["event_id"])
            if event_id not in latest:
                latest[event_id] = _parse_datetime_text(str(row["retrieved_at"]))
        return latest
