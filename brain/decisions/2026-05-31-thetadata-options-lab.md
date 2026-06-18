# ThetaData Options Research Lab

## Decision

Add a research-only options lab in PR #97 to test the SPY iron-condor hypothesis with real historical options quote data before any live execution work.

This decision implements the first code step after the options pivot described in PR #96. It does not authorize live trading.

## Why

The project needs evidence before more strategy work. The previous equity-news direction had too many public-information and latency disadvantages. The options pivot narrows the experiment to a specific, testable volatility-risk-premium hypothesis:

- SPY first.
- Defined-risk iron condors.
- Historical options data before broker integration.
- Honest backtests and OOS validation before paper/live trading.

ThetaData Value gives a low-cost path to real historical intraday option quote data, which is enough to start building and testing the plumbing.

## Implementation

PR #97 adds:

- DoltHub EOD options adapter.
- ThetaData intraday options adapter.
- Provider-neutral options models.
- SQLite migrations for:
  - EOD option chains,
  - volatility history,
  - intraday option quote bars,
  - EOD/intraday iron-condor backtest runs,
  - trade marks,
  - intraday trade explainability fields.
- Store helpers for option-chain, volatility, quote-bar, and backtest persistence.
- EOD iron-condor selection, backtesting, and sweeps.
- Intraday iron-condor selection, backtesting, diagnostics, and sweeps.
- Black-Scholes implied-vol and delta estimation for ThetaData quote bars where vendor Greeks are not available.
- Put-call parity and underlying-spot enrichment helpers.
- Markdown reports for backtests and sweeps.
- CLI commands for options backfill, coverage, diagnostics, backtests, and sweeps.

## Research-Only Boundaries

This PR does not:

- submit orders,
- call Alpaca,
- call E*Trade,
- use LLMs for trade decisions,
- claim edge,
- optimize on the five-day sample,
- commit the local SQLite database,
- commit generated report artifacts.

## Real-Data Smoke

Local ThetaData quote backfill completed for:

- Ticker: `SPY`
- Dates: `2026-05-18` through `2026-05-22`
- Time window: `09:45:00` through `15:45:00`
- Option quote rows: `558,828`

Diagnostics confirmed the local tape can produce valid intraday condor candidates.

The 72-combo sweep used:

- Entry times: `09:45:00`, `10:00:00`, `10:15:00`
- Target deltas: `0.12`, `0.16`, `0.20`
- Wing widths: `5`, `10`
- Profit targets: `25%`, `50%`
- Stop-loss multiples: `1.5`, `2.0`

Result:

- Every trade-producing configuration lost money over this tiny sample.
- Least-bad row:
  - `10:15:00` entry
  - `5`-wide wings
  - `0.12` target delta
  - `25%` profit target
  - `1.5x` stop
  - `3` trades
  - `0%` win rate
  - `-154.00` total PnL

Interpretation:

- This is not a strategy verdict.
- It is a useful plumbing verdict: the code can produce negative results and does not appear to be forcing attractive output.

## Validation

PR #97 validation:

```bash
git diff --cached --check
.venv/bin/python -m ruff check src tests
.venv/bin/python -m pytest -q
```

Result:

- Ruff clean.
- `955 passed, 1 warning`.
- Warning is an existing `websockets.legacy` deprecation from the Alpaca dependency path.

Real-data CLI smoke:

```bash
PYTHONPATH=src .venv/bin/python -m trader.cli options-backtest-intraday-iron-condor \
  --ticker SPY \
  --start 2026-05-18 \
  --end 2026-05-22 \
  --entry-time 10:15:00 \
  --selection-mode delta \
  --target-delta 0.12 \
  --wing-width 5 \
  --profit-target-pct 0.25 \
  --stop-loss-credit-multiple 1.5
```

```bash
PYTHONPATH=src .venv/bin/python -m trader.cli options-sweep-intraday-iron-condor \
  --ticker SPY \
  --start 2026-05-18 \
  --end 2026-05-22 \
  --entry-times 09:45:00,10:00:00,10:15:00 \
  --selection-mode delta \
  --target-deltas 0.12,0.16,0.20 \
  --wing-widths 5,10 \
  --profit-targets 0.25,0.50 \
  --stop-loss-multiples 1.5,2.0
```

## Follow-Ups

1. Merge or reconcile PR #96 so `brain/27` is available on `main`.
2. Review PR #97 as a research infrastructure PR, not a live-trading PR.
3. Build a multi-year ThetaData backfill plan with resumability and quality reports.
4. Add VIX and economic-calendar entry filters.
5. Add explicit options slippage and fee models.
6. Add locked OOS evaluation for the options lab.
7. Defer Alpaca paper/live execution until the research gate passes.

## Current PRs To Read

- PR #96: options pivot briefing and issue-comment discussion.
- PR #97: ThetaData options research lab implementation.
