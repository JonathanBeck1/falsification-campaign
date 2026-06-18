# Options Research Platform

A memory-safe, multi-strategy, overfitting-resistant backtest stack built on top
of the `option_quote_bars_1m` firehose. Everything streams **one trade-date at a
time**, so a full year of intraday quotes never has to fit in RAM.

> Research only. None of this places orders or constitutes live-trading evidence.
> Results produced from the small synthetic test fixtures are **not** research
> conclusions.

## How the pieces fit

```
                 ┌─────────────────────────────────────────────┐
                 │            QuoteSource (protocol)            │
                 │  iter_days() -> one (date, [bars]) at a time │
                 ├───────────────────────┬─────────────────────┤
                 │  SqliteQuoteSource     │   LakeQuoteSource    │
                 │  (Store, 1 query/day)  │ (DuckDB partition    │
                 │                        │  pushdown, 1 day)    │
                 └───────────┬────────────┴──────────┬──────────┘
                             │                        │
                             ▼                        ▼
        ┌──────────────────────────────┐   ┌──────────────────────────┐
        │ intraday.py (iron condor)     │   │ short_put.py             │
        │ run_intraday_iron_condor_…    │   │ run_short_put_backtest   │
        │ streams day-by-day, ≤1 day    │   │ streams day-by-day        │
        └───────────────┬───────────────┘   └───────────┬──────────────┘
                        │  closed trades                 │
                        ▼                                ▼
        ┌───────────────────────────────────────────────────────────┐
        │ metrics.py  (pure)  →  reporting.py  (md + json + equity csv)│
        │ benchmark.py (buy-and-hold alpha)                            │
        └───────────────────────────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │ walkforward.py — train/test folds, in-sample vs OOS,         │
        │ per-fold degradation (the anti-overfitting guard)            │
        └───────────────────────────────────────────────────────────┘

        quality.py — NBBO data-quality report (crossed/locked/wide/gaps),
        also streamed one trade-date at a time.
```

### Modules

| Module | Responsibility |
|---|---|
| `options/sources.py` | `QuoteSource` protocol + `SqliteQuoteSource` / `LakeQuoteSource`. Yields one `(trade_date, bars)` at a time. |
| `options/intraday.py` | Iron-condor engine. Streams day-by-day; accepts a list, a replay tape, or a `QuoteSource`. |
| `options/short_put.py` | Cash-secured short-put engine on the same streaming foundation. |
| `options/metrics.py` | Pure, I/O-free metrics over closed trades / equity curve. |
| `options/reporting.py` | Standardized markdown report + machine-readable JSON + equity CSV. |
| `options/benchmark.py` | Underlying buy-and-hold return and alpha (excess vs benchmark). |
| `options/walkforward.py` | Sequential train/test folds, leak-free out-of-sample evaluation. |
| `options/quality.py` | Coverage + NBBO quote-quality diagnostics. |

### Why streaming matters

The first iteration loaded an entire date window into memory (~100M+
`OptionQuoteBar` objects for a year) and OOM'd on a 16 GB machine. Every engine
here now pulls **one trade-date**, processes it, and releases it before reading
the next. The `tests/financial/test_quote_sources.py` memory-safety test proves
the engine never accumulates more than a single day (weakref + gc).

## Memory-safe full-data runbook (run later)

Do **not** run these against the live dataset while the ThetaData backfill is
writing `data/trader.sqlite`. Once the backfill finishes:

### 1. Export the lake once

```bash
.venv/bin/python -m trader.cli options-export-parquet-lake \
  --ticker QQQ --out lake
```

This reads SQLite read-only and writes a date-partitioned Parquet lake under
`./lake`. Do this a single time; every later command reads the lake.

### 2. Backtests / sweeps against the lake, in monthly chunks

```bash
# Iron condor, one month at a time (DuckDB reads only that month's partitions)
.venv/bin/python -m trader.cli options-backtest-intraday-iron-condor \
  --ticker QQQ --start 2021-01-01 --end 2021-01-31 \
  --source lake --lake-path lake --output out/qqq-2021-01.md

# Cash-secured short put
.venv/bin/python -m trader.cli options-backtest-short-put \
  --ticker QQQ --start 2021-01-01 --end 2021-01-31 \
  --source lake --lake-path lake --output out/qqq-sp-2021-01.md

# Parameter sweep (materializes one month's tape, reuses across combos)
.venv/bin/python -m trader.cli options-sweep-intraday-iron-condor \
  --ticker QQQ --start 2021-01-01 --end 2021-01-31 \
  --source lake --lake-path lake --output out/qqq-sweep-2021-01.md
```

### 3. Walk-forward (out-of-sample) over the full range

```bash
.venv/bin/python -m trader.cli options-walkforward-intraday-iron-condor \
  --ticker QQQ --start 2021-01-01 --end 2021-12-31 \
  --train-days 90 --test-days 30 \
  --source lake --lake-path lake --output out/qqq-walkforward-2021.md
```

Each fold loads only its bounded train/test window, so memory stays proportional
to a single fold — never the whole year.

### 4. Data-quality check before trusting any result

```bash
.venv/bin/python -m trader.cli options-data-quality-report \
  --ticker QQQ --start 2021-01-01 --end 2021-12-31 \
  --source lake --lake-path lake --output out/qqq-quality-2021.md
```

Flags crossed/locked quotes, non-positive sizes, absurd spreads, per-expiration
coverage gaps, and minutes-present per day — all streamed one trade-date at a
time.

## Tests & CI

All unit tests live in `tests/financial/` and run on tiny synthetic fixtures.
CI (`.github/workflows/ci.yml`) runs `ruff check src tests` and `pytest -q`,
which auto-collects everything under `tests/` (including
`test_quote_sources.py`, `test_metrics.py`, `test_benchmark.py`,
`test_short_put.py`, `test_walkforward.py`, and `test_data_quality.py`).
`duckdb` is a core dependency, so the SQLite↔lake parity tests execute in CI
rather than skip.
