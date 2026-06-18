"""Read the options firehose from a Parquet lake (local dir or object storage).

This is the read side of the data-sharing architecture. The lake is produced by
`scripts/export_parquet_lake.py` and holds `option_quote_bars_1m` as Parquet,
hive-partitioned by `trade_date`. Any reader points at the same lake --
a local directory, or an `s3://` / R2 / Supabase-Storage path -- and query it
with DuckDB, which pushes `trade_date` filters down to the partition layout so a
backtest only reads the days it touches.

The public method mirrors `Store.get_option_quote_bars_1m` so callers can swap a
`Store` for a `ParquetLake` without changing their query shape.

Object storage (R2 / S3) credentials are read from the environment, never code:
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY   (S3 or R2 token)
    LAKE_S3_ENDPOINT                             (R2 endpoint, e.g.
                                                  https://<acct>.r2.cloudflarestorage.com)
    LAKE_S3_REGION                               (default: auto)
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trader.options.models import OptionQuoteBar

FIREHOSE_TABLE = "option_quote_bars_1m"


class ParquetLake:
    """DuckDB-backed reader over a date-partitioned Parquet options lake."""

    def __init__(self, base_path: str, *, table: str = FIREHOSE_TABLE) -> None:
        """`base_path` is the lake root: a local dir, or `s3://bucket/lake`."""
        self._base = base_path.rstrip("/")
        self._table = table
        self._glob = f"{self._base}/{table}/**/*.parquet"

    # -- connection -------------------------------------------------------

    def _connect(self) -> Any:
        import duckdb

        con = duckdb.connect()
        if self._base.startswith(("s3://", "r2://", "gcs://")):
            con.execute("INSTALL httpfs; LOAD httpfs;")
            endpoint = os.environ.get("LAKE_S3_ENDPOINT")
            region = os.environ.get("LAKE_S3_REGION", "auto")
            key = os.environ.get("AWS_ACCESS_KEY_ID")
            secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
            # Configure an S3-compatible secret (works for AWS S3 and, with an
            # endpoint override, Cloudflare R2). Credentials come from env only.
            parts = ["TYPE s3", f"REGION '{region}'"]
            if key and secret:
                parts += [f"KEY_ID '{key}'", f"SECRET '{secret}'"]
            if endpoint:
                host = endpoint.replace("https://", "").replace("http://", "")
                parts += [f"ENDPOINT '{host}'", "URL_STYLE 'path'", "USE_SSL true"]
            con.execute(f"CREATE OR REPLACE SECRET lake (\n  {', '.join(parts)}\n);")
        return con

    # -- queries ----------------------------------------------------------

    def get_option_quote_bars_1m(
        self,
        ticker: str,
        *,
        since: str | None = None,
        until: str | None = None,
        trade_date: str | None = None,
        expiration: str | None = None,
    ) -> list[OptionQuoteBar]:
        """Return 1-minute option quote bars, mirroring Store's signature.

        Filters on `trade_date` are pushed down to the hive partition layout, so
        bounded date ranges read only the relevant partition directories.
        """
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

        sql = f"""
            SELECT quote_ts, ticker, expiration, strike, call_put, bid, ask,
                   underlying_price, bid_size, ask_size, bid_exchange, ask_exchange,
                   bid_condition, ask_condition, source
            FROM read_parquet(?, hive_partitioning = true)
            WHERE {" AND ".join(clauses)}
            ORDER BY quote_ts ASC, expiration ASC, strike ASC, call_put ASC
        """
        con = self._connect()
        try:
            rows = con.execute(sql, [self._glob, *params]).fetchall()
        finally:
            con.close()

        return [
            OptionQuoteBar(
                timestamp=_as_dt(r[0]),
                ticker=r[1],
                expiration=_as_date(r[2]),
                strike=float(r[3]),
                call_put=r[4],
                bid=r[5],
                ask=r[6],
                underlying_price=r[7],
                bid_size=r[8],
                ask_size=r[9],
                bid_exchange=r[10],
                ask_exchange=r[11],
                bid_condition=r[12],
                ask_condition=r[13],
                source=r[14],
            )
            for r in rows
        ]

    def get_decision_bars(
        self,
        ticker: str,
        *,
        since: str,
        until: str,
        times: list[str],
        strike_band: float = 0.15,
        dte_lo: int = 0,
        dte_hi: int = 60,
    ) -> list[OptionQuoteBar]:
        """FAST 'screening' read: only the decision-relevant minute bars.

        Returns bars whose local time-of-day is in ``times`` (e.g. market open,
        entry time, exit-decision time, market close), whose strike is within
        ``strike_band`` of the underlying, and whose DTE is in ``[dte_lo, dte_hi]``.
        This is ~100x fewer rows than the full window, pushed down into DuckDB.

        APPROXIMATE: it reproduces the trade structure (entries, win rate, verdict)
        but NOT the exact P&L, because the full per-minute marking lands exits at
        different prices. Use it to *screen* configs fast; confirm finalists with a
        full-resolution backtest.
        """
        from trader.options.models import OptionQuoteBar

        if not times:
            return []
        placeholders = ", ".join(["?"] * len(times))
        sql = f"""
            SELECT quote_ts, ticker, expiration, strike, call_put, bid, ask,
                   underlying_price, bid_size, ask_size, bid_exchange, ask_exchange,
                   bid_condition, ask_condition, source
            FROM read_parquet(?, hive_partitioning = true)
            WHERE ticker = ?
              AND trade_date >= ? AND trade_date <= ?
              AND regexp_extract(quote_ts, '[T ](\\d{{2}}:\\d{{2}}:\\d{{2}})', 1) IN ({placeholders})
              AND underlying_price IS NOT NULL
              AND abs(strike / underlying_price - 1.0) <= ?
              AND datediff('day', CAST(trade_date AS DATE), CAST(expiration AS DATE)) BETWEEN ? AND ?
            ORDER BY quote_ts ASC, expiration ASC, strike ASC, call_put ASC
        """
        params: list[Any] = [
            self._glob,
            ticker.strip().upper(),
            since,
            until,
            *times,
            strike_band,
            dte_lo,
            dte_hi,
        ]
        con = self._connect()
        try:
            rows = con.execute(sql, params).fetchall()
        finally:
            con.close()
        return [
            OptionQuoteBar(
                timestamp=_as_dt(r[0]),
                ticker=r[1],
                expiration=_as_date(r[2]),
                strike=float(r[3]),
                call_put=r[4],
                bid=r[5],
                ask=r[6],
                underlying_price=r[7],
                bid_size=r[8],
                ask_size=r[9],
                bid_exchange=r[10],
                ask_exchange=r[11],
                bid_condition=r[12],
                ask_condition=r[13],
                source=r[14],
            )
            for r in rows
        ]

    def available_dates(self, ticker: str | None = None) -> list[str]:
        """List distinct trade_dates present in the lake (cheap; partition scan)."""
        where = ""
        params: list[Any] = [self._glob]
        if ticker is not None:
            where = "WHERE ticker = ?"
            params.append(ticker.strip().upper())
        sql = (
            f"SELECT DISTINCT trade_date FROM read_parquet(?, hive_partitioning = true) "
            f"{where} ORDER BY trade_date"
        )
        con = self._connect()
        try:
            return [str(r[0]) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
