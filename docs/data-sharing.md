# Sharing the options data across machines

> **Faster backfills — `--bulk-load`.** For large multi-year pulls (especially
> onto an external SSD), add `--bulk-load` to `options-backfill-thetadata-quotes`.
> It batches each day's ~270k-row insert into a **single transaction** and relaxes
> durability PRAGMAs (`synchronous=NORMAL`, larger cache, `temp_store=MEMORY`) —
> crash-safe under WAL. Without it, the autocommit connection fsyncs **once per
> row**, which is the dominant cost on a slow external drive. It is OFF by default
> so the normal path is unchanged; it does NOT affect data correctness (validated
> byte-identical + idempotent). Recommended for every fresh ticker backfill.
>
> **Don't run two ticker backfills at once on the ThetaData VALUE tier** — it's a
> single concurrent thread + a shared 30 req/min cap, and SQLite has a single
> writer lock, so parallel runs only contend. Queue tickers sequentially; the
> ledger keys on `(ticker, trade_date)`. True parallelism needs a higher
> ThetaData tier (more threads) + separate DB files or Postgres.



One git repo, a large local options dataset, and more than one machine that
needs it. The code is already shared via git; this doc covers sharing the **data**.

## The split: firehose vs app layer

The data has two very different shapes, so it lives in two places:

| Layer | What | Where | Why |
|---|---|---|---|
| **Firehose** | `option_quote_bars_1m` — ~480M rows / ~135 GB SQLite (≈30 GB Parquet) | **Parquet lake** in object storage (Cloudflare R2 / S3 / Supabase Storage), queried with **DuckDB** | Immutable, append-only, scanned in bulk by backtests. Columnar + partitioned = cheap & fast; object storage is cheap and (on R2) egress-free. |
| **App / results** | backtest runs & results, annotations, lake catalog | **Supabase Postgres** | Small, relational, multi-writer, frequently updated. Exactly what Postgres is for. |

Putting 480M quote rows in hosted Postgres would be slow to scan and rack up
egress on every backtest. Putting collaborative app state in Parquet would be
painful (no concurrent writes). Each tool does what it's good at.

## 1. Export the firehose to Parquet (run AFTER the backfill finishes)

```bash
# Full export of all completed SPY days:
.venv/bin/python scripts/export_parquet_lake.py --db data/trader.sqlite --out lake --ticker SPY

# Later, incremental "push new days" after a fresh pull:
.venv/bin/python scripts/export_parquet_lake.py --db data/trader.sqlite --out lake --ticker SPY --since 2026-06-02
```

Output layout (hive-partitioned by date):

```
lake/
  manifest.json
  option_quote_bars_1m/
    trade_date=2020-01-02/data_0.parquet
    trade_date=2020-01-03/data_0.parquet
    ...
```

> The SQLite DB is attached **READ_ONLY**, so the export is safe even if the
> backfill is still running — but it's I/O heavy, so prefer to run it once the
> pull is done to avoid contending for the SSD.

## 2. Deliver the lake (pick one — decide later)

- **Local copy** (friend nearby / occasional refresh): `rsync -a lake/ /Volumes/HisDrive/lake/` or copy to his machine. Cheapest, no accounts.
- **Object storage** (friend remote / needs fresh data): sync once, then deltas are free.
  ```bash
  rclone sync lake/ r2:my-bucket/lake/      # Cloudflare R2 — zero egress (recommended)
  aws s3 sync   lake/ s3://my-bucket/lake/   # AWS S3
  ```

## 3. Query the lake (either dev, either delivery)

```python
from trader.storage.parquet_lake import ParquetLake

# Local copy:
lake = ParquetLake("lake")
# ...or object storage (creds via env: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY,
#    plus LAKE_S3_ENDPOINT for R2):
lake = ParquetLake("s3://my-bucket/lake")

bars = lake.get_option_quote_bars_1m("SPY", since="2024-01-02", until="2024-06-30")
```

`ParquetLake.get_option_quote_bars_1m(...)` mirrors `Store.get_option_quote_bars_1m(...)`,
so a backtest can take either a `Store` (local SQLite) or a `ParquetLake`
(shared lake) with no other changes. Date filters are pushed down to the
partition layout, so a bounded range only reads the days it needs.

## 4. The Supabase app layer

The small relational app/results state (tables: `lake_partitions`,
`backtest_runs`, `backtest_results`, `annotations`) is designed to live in a
Postgres instance such as Supabase, separate from the immutable Parquet
firehose. The migration SQL is not shipped in this public snapshot.

Setup (when you're ready — has cost, needs sign-off):
1. Create a **dedicated** Supabase project for trader (keep it separate from
   other projects). Pro plan ($25/mo) avoids the free tier's 1-week auto-pause.
2. Apply the app-layer schema (Supabase MCP `apply_migration`, or `supabase db push`).
3. Connect with the project URL + anon key (client) or the connection
   string (scripts). Keep secrets in `.env`, never committed.
4. After each export, upsert the manifest into `lake_partitions` so the app
   knows what data exists without listing object storage.

## Cost (within ~$25/mo)

| Piece | Host | Monthly |
|---|---|---|
| Firehose (~30 GB Parquet) | Cloudflare R2 (zero egress) | ~$0.50 |
| App / results layer | Supabase Pro | $25 |
