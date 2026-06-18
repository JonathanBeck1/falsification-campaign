"""Export the SQLite options firehose to a date-partitioned Parquet lake.

This is the "firehose" half of the data-sharing architecture: the large,
immutable, analytical option-quote table is exported once to compressed,
date-partitioned Parquet. Any machine then queries that lake directly
with DuckDB (locally, or from object storage such as Cloudflare R2 / S3 /
Supabase Storage). The small, frequently-updated app/results state lives separately
in a Postgres app layer (schema not shipped in this public snapshot).

The matching read side is `trader.storage.parquet_lake.ParquetLake`. The thin
CLI wrapper lives in `scripts/export_parquet_lake.py`, and the first-class CLI
subcommand `options-export-parquet-lake` both call `export_lake` here so the
export logic has a single, importable, testable home.

Safety:
  * The SQLite database is attached READ_ONLY, so this can run even while the
    backfill is still writing (WAL mode allows concurrent readers). That said,
    a full export is I/O heavy -- prefer to run it AFTER the backfill finishes
    so the two jobs don't contend for the SSD.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

# The single big analytical table. Everything else (EOD chains, vol history) is
# small enough to live in the Supabase app layer if desired.
FIREHOSE_TABLE = "option_quote_bars_1m"


def _build_where(ticker: str | None, since: str | None, until: str | None) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if ticker:
        clauses.append("ticker = ?")
        params.append(ticker.strip().upper())
    if since:
        clauses.append("trade_date >= ?")
        params.append(since)
    if until:
        clauses.append("trade_date <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def export_lake(
    *,
    db_path: Path,
    out_dir: Path,
    ticker: str | None,
    since: str | None,
    until: str | None,
    row_group_size: int = 122_880,
) -> dict[str, object]:
    """Export the firehose table to `out_dir` as Parquet partitioned by trade_date.

    Returns a manifest dict describing what was written.
    """
    import duckdb

    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    table_out = out_dir / FIREHOSE_TABLE
    where, params = _build_where(ticker, since, until)

    con = duckdb.connect()
    try:
        con.execute("INSTALL sqlite; LOAD sqlite;")
        # READ_ONLY so we never risk the live backfill's writer.
        con.execute(f"ATTACH '{db_path.as_posix()}' AS src (TYPE sqlite, READ_ONLY);")

        # Pre-flight: count rows and the date span we're about to export so the
        # caller gets a manifest even on an empty/no-op run.
        stats = con.execute(
            f"SELECT COUNT(*), MIN(trade_date), MAX(trade_date), "
            f"COUNT(DISTINCT trade_date) FROM src.{FIREHOSE_TABLE}{where}",
            params,
        ).fetchone()
        total_rows, min_date, max_date, n_days = stats
        if not total_rows:
            return {
                "table": FIREHOSE_TABLE,
                "rows": 0,
                "days": 0,
                "note": "no rows matched the filter; nothing exported",
                "filter": {"ticker": ticker, "since": since, "until": until},
            }

        # Partitioned, zstd-compressed COPY. OVERWRITE_OR_IGNORE lets an
        # incremental run re-write only the touched date partitions without
        # clobbering the rest of the lake.
        # DuckDB COPY can't use bind params, so inline-validate + format safely.
        copy_sql = f"""
            COPY (
                SELECT * FROM src.{FIREHOSE_TABLE}{_inline_where(ticker, since, until)}
            ) TO '{table_out.as_posix()}'
            (FORMAT PARQUET, PARTITION_BY (trade_date), COMPRESSION zstd,
             ROW_GROUP_SIZE {row_group_size}, OVERWRITE_OR_IGNORE true);
        """
        con.execute(copy_sql)
    finally:
        con.close()

    manifest = {
        "table": FIREHOSE_TABLE,
        "rows": int(total_rows),
        "days": int(n_days),
        "date_range": [min_date, max_date],
        "partition_scheme": "trade_date=YYYY-MM-DD (hive)",
        "compression": "zstd",
        "filter": {"ticker": ticker, "since": since, "until": until},
        "source_db": str(db_path),
        "out_dir": str(table_out),
        "exported_at": datetime.now(UTC).isoformat(),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _inline_where(ticker: str | None, since: str | None, until: str | None) -> str:
    """Build a safely-escaped WHERE clause for the COPY statement.

    Values come from CLI args (dates / a ticker symbol). We still validate
    shape and single-quote-escape to avoid any SQL surprises.
    """
    clauses: list[str] = []
    if ticker:
        sym = ticker.strip().upper()
        if not sym.isalnum():
            raise ValueError(f"suspicious ticker symbol: {ticker!r}")
        clauses.append(f"ticker = '{sym}'")
    for col, val in (("trade_date >=", since), ("trade_date <=", until)):
        if val:
            _validate_date(val)
            clauses.append(f"{col} '{val}'")
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _validate_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}") from exc
