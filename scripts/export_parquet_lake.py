#!/usr/bin/env python
"""Export the SQLite options firehose to a date-partitioned Parquet lake.

This is the "firehose" half of the data-sharing architecture: the large,
immutable, analytical option-quote table is exported once to compressed,
date-partitioned Parquet. Any machine then queries that lake directly
with DuckDB (locally, or from object storage such as Cloudflare R2 / S3 /
Supabase Storage). The small, frequently-updated app/results state lives separately
in a Postgres app layer (schema not shipped in this public snapshot).

Why DuckDB + Parquet (not "load 480M rows into Postgres"):
  * Option-quote data compresses ~4x (zstd): ~135 GB SQLite -> ~30 GB Parquet.
  * Hive date-partitioning + columnar pushdown means a backtest that filters
    `trade_date BETWEEN ...` only reads the partitions it touches.
  * Object storage is cheap and (on R2) egress-free, so repeated backtest
    scans from any machine cost nothing in bandwidth.

Safety:
  * The SQLite database is attached READ_ONLY, so this can run even while the
    backfill is still writing (WAL mode allows concurrent readers). That said,
    a full export is I/O heavy -- prefer to run it AFTER the backfill finishes
    so the two jobs don't contend for the SSD.

The export logic itself lives in `trader.storage.parquet_export.export_lake`
so it can be imported and tested directly (and reused by the
`options-export-parquet-lake` CLI subcommand). This module is a thin CLI shim.

Usage:
  # Full export of every completed day for SPY:
  .venv/bin/python scripts/export_parquet_lake.py \
      --db data/trader.sqlite --out lake --ticker SPY

  # Incremental: only export days on/after a date (cheap "push new days"):
  .venv/bin/python scripts/export_parquet_lake.py \
      --db data/trader.sqlite --out lake --ticker SPY --since 2024-01-01

Then sync `lake/` to object storage, e.g.:
  rclone sync lake/ r2:my-bucket/lake/      # Cloudflare R2 (zero egress)
  aws s3 sync   lake/ s3://my-bucket/lake/   # AWS S3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `trader` importable when this script is run directly (python scripts/...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trader.storage.parquet_export import _validate_date, export_lake


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="data/trader.sqlite", help="path to the SQLite database")
    parser.add_argument("--out", default="lake", help="output directory for the Parquet lake")
    parser.add_argument("--ticker", default=None, help="restrict export to one ticker (e.g. SPY)")
    parser.add_argument("--since", default=None, help="only export trade_date >= this (YYYY-MM-DD)")
    parser.add_argument("--until", default=None, help="only export trade_date <= this (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    for d in (args.since, args.until):
        if d:
            _validate_date(d)

    try:
        manifest = export_lake(
            db_path=Path(args.db),
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


if __name__ == "__main__":
    raise SystemExit(main())
