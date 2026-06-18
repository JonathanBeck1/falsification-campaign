# Outcome Review V1

Date: 2026-05-20
Status: accepted

## Decision

Add a CLI/report-only `outcome-review` workflow before adding UI polish.

## Why

The first SPY outcome report proved the backtester works, but the current local
sample is still too small to infer edge. A second-pass review should make that
obvious every time by separating usable samples, watchlist buckets, and junk
buckets.

Keeping V1 CLI/report-only lets us stabilize the review logic before the larger
dashboard redesign. The future Streamlit view can read the same Markdown output
or call the same review module.

## Boundaries

- Research-only.
- No broker calls.
- No market data fetches.
- No database writes.
- No Streamlit changes in this branch.
- No edge claims without enough sample depth and later cost/slippage checks.

## Next Questions

- Which event classes deserve collection priority?
- What `min_sample` should be standard for intraday buckets?
- Which horizons should survive after more data arrives?
- When should we add transaction cost and slippage assumptions?
- Which review sections should be promoted into the UI polish branch?
