# Data Quality And Backfill Controls

## Decision

Add a durable `source_fetches` ledger and make every ingestion path report source health into it. Expose the same ledger through CLI commands and the Streamlit terminal.

## Why

The pipeline needs operator visibility before any strategy work can be trusted. A news-driven system silently fails when a feed goes empty, rate-limits, or returns malformed data. The old dashboard showed stored event volume but could not answer whether a source was healthy, empty, or failing during the latest fetch.

## Implementation

- Added `source_fetches` with attempted time, status, item count, persisted count, latency, lookback window, and error text.
- Added `StoreSourceHealthTracker` and `CompositeSourceTracker` so fetch freshness and durable source quality can share the same ingestion hooks.
- Wired `run_one_day`, `fetch-events`, and `backfill-events` through store-backed source tracking.
- Added CLI commands:
  - `source-health --limit N`
  - `backfill-events --source SOURCE --lookback-days N`
- Added terminal source quality rows and SYSTEM source health panels.
- Added operator alerts when a source's latest fetch status is `error`.

## Safety Boundaries

- No live trading behavior changed.
- No paid APIs or secrets are required.
- Backfill commands persist normalized events only.
- Terminal changes remain visibility-only and do not introduce trading controls.

## Verification

- `ruff check .`
- `python -m py_compile apps/dashboard.py`
- `python -m pytest tests/financial -v`
- Streamlit smoke check confirmed NEWS DESK still loads and SYSTEM renders healthy, degraded, and failing source statuses.
