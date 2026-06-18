# Options Research Lab Handoff

Status: handoff doc for PR #97. Read with PR #96's `brain/27_options_pivot_briefing.md` and its issue comment before continuing.

## Source Of Truth Chain

The current options direction is spread across open branches, so do not rely only on `main`:

1. `main` contains `brain/00` through `brain/24`, mostly written for the earlier equity-news system.
2. PR #93 proposes `brain/25_horse_race_protocol.md` and `brain/26_alignment_2026Q2.md`.
3. PR #96 proposes `brain/27_options_pivot_briefing.md`.
4. PR #96's issue comment adds the latest operating decisions from the collaborator and Claude.
5. PR #97 adds the first real options research implementation.

If these sources conflict, use this precedence until the docs are merged and reconciled:

1. PR #96 issue comment for broker/data/operating-model decisions.
2. PR #96 `brain/27_options_pivot_briefing.md` for strategic direction.
3. This handoff doc for what PR #97 actually built.
4. Older `brain/00` through `brain/24` only where they do not conflict.

## Strategic Direction

The active strategy hypothesis is no longer a broad equity-news trading system. The current research focus is:

> Sell defined-risk SPY iron condors, initially 30-45 DTE, near 16-delta short strikes, with explicit VIX/calendar/risk filters, and prove or reject the edge with point-in-time historical options data before live execution.

The working assumption is that news becomes a risk filter, not the alpha source:

- FOMC/CPI/NFP calendars can block new condor entries around known volatility events.
- SEC/news/LLM infrastructure is not the near-term trading engine.
- The project should not add new live execution behavior until backtests and paper tests pass.

## Broker And Data Direction

PR #96 originally discussed E*Trade plus a separate historical options vendor. The later PR #96 issue comment updates the working direction:

- Alpaca Algo Trader Plus is the preferred live broker/data candidate if options permissions and data coverage satisfy the need.
- ThetaData Value is now the active historical intraday options data source for the research lab.
- Polygon/ORATS/CBOE remain possible alternatives if ThetaData coverage or quality is insufficient.
- SPY is the starting instrument.
- QQQ is a later bucket after SPY has enough evidence.
- SPX is a likely long-term upgrade after SPY because SPX has tax, settlement, and assignment advantages, but SPX sizing is larger and should not be the first implementation target.

## Operating Model

The preferred live model is hybrid:

- Bot scans and proposes candidate entries.
- Human approves entries from a mobile notification.
- No approval means no trade.
- Once a position is open, exits and risk controls can be automated.
- Alerts are required for fills, exits, drawdowns, and kill-switch events.

Live trading remains out of scope until the research gate is passed.

## What PR #97 Built

PR #97 creates a research-only options lab. It does not place live trades.

New data adapters:

- `src/trader/adapters/dolthub/options.py`
  - Pulls normalized EOD options-chain and volatility-history style data from DoltHub's `post-no-preference/options` repository.
- `src/trader/adapters/thetadata/options.py`
  - Wraps the ThetaData Python client.
  - Normalizes option contracts, option quote bars, and underlying quote bars into internal models.

New options package:

- `src/trader/options/models.py`
  - Provider-neutral option quote, contract, volatility-history, option quote bar, and underlying quote bar models.
- `src/trader/options/iron_condor.py`
  - EOD iron-condor selection.
- `src/trader/options/backtest.py`
  - EOD iron-condor backtest harness.
- `src/trader/options/sweep.py`
  - EOD parameter sweep support.
- `src/trader/options/greeks.py`
  - Black-Scholes pricing, implied-vol solving, and delta estimation.
- `src/trader/options/underlying.py`
  - Put-call parity spot inference and underlying-spot attachment.
- `src/trader/options/intraday.py`
  - Intraday quote-based iron-condor backtest.
  - Supports premium-based selection and estimated-delta selection.
  - Emits per-trade deltas, max favorable PnL, max adverse PnL, and mark count.
- `src/trader/options/intraday_diagnostics.py`
  - Explains whether the intraday quote tape can actually form valid condors.
- `src/trader/options/intraday_sweep.py`
  - Runs parameter sweeps over intraday quote data.
  - Reuses timestamp-indexed replay data so sweeps do not rebuild the quote tape for every parameter combination.
- `src/trader/options/quality.py`
  - Coverage and quality checks for options data.
- `src/trader/options/reporting.py`
  - Markdown report rendering helpers.

New migrations:

- `m0004_options_lab.py`
  - EOD options chain, volatility history, EOD iron-condor runs/trades/marks.
- `m0005_options_intraday.py`
  - Intraday option quote bars and intraday iron-condor runs/trades/marks.
- `m0006_option_quote_underlying_price.py`
  - Adds point-in-time underlying spot to intraday option quote bars.
- `m0007_intraday_trade_explainability.py`
  - Adds short-leg deltas, MAE/MFE, and mark count to intraday trade rows.

New CLI commands:

- `options-backfill-dolthub`
- `options-coverage-report`
- `options-backtest-iron-condor`
- `options-sweep-iron-condor`
- `options-backfill-thetadata-quotes`
- `options-backtest-intraday-iron-condor`
- `options-diagnose-intraday-iron-condor`
- `options-sweep-intraday-iron-condor`

## Local Data Already Pulled

Local data artifacts are intentionally not committed.

The local development DB currently has a real ThetaData smoke sample:

- Ticker: `SPY`
- Dates: `2026-05-18` through `2026-05-22`
- Window: `09:45:00` through `15:45:00`
- Expiration selection: one 30-45 DTE expiration per trade date
- Strike range: `80`
- Option quote rows persisted: `558,828`
- Underlying spot: inferred/enriched through the current quote path

Generated local reports:

- `output/reports/spy-intraday-diagnostics-2026-05-18-2026-05-22.md`
- `output/reports/spy-intraday-sweep-2026-05-18-2026-05-22.md`
- `output/reports/spy-intraday-backtest-explainability-2026-05-18-2026-05-22.md`

These are ignored/local research artifacts, not source-controlled deliverables.

## First Real Result

The first real ThetaData sweep is not evidence of edge. It is a plumbing smoke test.

Sweep:

- Ticker: `SPY`
- Dates: `2026-05-18` through `2026-05-22`
- Entry times: `09:45:00`, `10:00:00`, `10:15:00`
- Selection mode: estimated delta
- Target deltas: `0.12`, `0.16`, `0.20`
- Wings: `5`, `10`
- Profit targets: `25%`, `50%`
- Stop multiples: `1.5`, `2.0`
- Total combinations: `72`

Result:

- Every trade-producing configuration lost money on this five-day sample.
- Least-bad row:
  - Entry: `10:15:00`
  - Wing: `5`
  - Delta: `0.12`
  - Profit target: `25%`
  - Stop multiple: `1.5`
  - Trades: `3`
  - Win rate: `0%`
  - Total PnL: `-154.00`
  - Max drawdown: `154.00`

Interpretation:

- The code is giving a plausible negative result instead of manufacturing a good-looking backtest.
- This sample is far too small to accept or reject the strategy.
- Next evidence requires a multi-year ThetaData backfill and a pre-registered OOS split.

## Important Commands

Backfill real ThetaData quotes:

```bash
PYTHONPATH=src .venv/bin/python -m trader.cli options-backfill-thetadata-quotes \
  --ticker SPY \
  --start 2026-05-18 \
  --end 2026-05-22 \
  --start-time 09:45:00 \
  --end-time 15:45:00 \
  --strike-range 80
```

Run diagnostics:

```bash
PYTHONPATH=src .venv/bin/python -m trader.cli options-diagnose-intraday-iron-condor \
  --ticker SPY \
  --start 2026-05-18 \
  --end 2026-05-22 \
  --entry-time 10:15:00 \
  --selection-mode delta \
  --target-delta 0.12
```

Run one intraday backtest:

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

Run the smoke sweep:

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

Verify PR #97:

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m pytest -q
```

Most recent PR #97 verification:

- Ruff: clean.
- Pytest: `955 passed, 1 warning`.
- Warning: existing `websockets.legacy` deprecation from Alpaca dependency path.

## Credentials And Secrets

Do not commit ThetaData credentials.

The intended local setup is:

```bash
mkdir -p ~/.thetadata
nano ~/.thetadata/creds.txt
chmod 600 ~/.thetadata/creds.txt
```

Then point `.env` at that file:

```bash
THETADATA_CREDENTIALS_FILE=/Users/yourname/.thetadata/creds.txt
```

Raw provider credentials should stay outside the repo even when the repo is private. The repo can be shared with collaborators, pushed to GitHub, cloned into worktrees, or exposed in logs. A local credentials file keeps accidental leakage risk much lower.

## What Not To Do Next

Do not:

- Build live trading.
- Add Alpaca live execution.
- Treat the five-day result as evidence.
- Add more LLM decision logic.
- Optimize parameters on the five-day sample.
- Merge more equity-news strategy work without reconciling it against the options pivot.
- Commit the SQLite DB or generated reports.

## Next Build Priorities

1. Merge or reconcile PR #96 so `brain/27` is available on `main`.
2. Keep PR #97 reviewable; do not mix live execution into it.
3. Add a multi-year ThetaData backfill plan:
   - date partitioning,
   - retry/resume ledger,
   - quote quality report,
   - storage-size estimate,
   - expected runtime.
4. Add VIX/calendar filters to the options backtest:
   - no entries around FOMC/CPI/NFP,
   - no entries when VIX percentile breaches the pre-registered threshold.
5. Add transaction-cost and slippage assumptions explicitly:
   - per-leg spread crossing,
   - per-contract fees,
   - conservative fill rules.
6. Add OOS split support for the options lab:
   - no parameter tuning on the locked period,
   - report selection window separately from OOS window.
7. Only after a credible backtest passes: design Alpaca paper/live integration.

## Agent Handoff Prompt

Use this prompt when moving the project to another AI agent:

```text
You are working in <your-handle>/trader. Before coding, read these in order:

1. brain/00_project_north_star.md
2. brain/10_llm_agent_boundaries.md
3. brain/24_edge_validation_criteria.md
4. PR #96: brain/27_options_pivot_briefing.md
5. PR #96 issue comment by the collaborator
6. PR #97 body and diff
7. brain/28_options_research_lab_handoff.md
8. brain/decisions/2026-05-31-thetadata-options-lab.md

Current direction: research-only SPY iron-condor options lab using ThetaData historical intraday options data. Do not add live trading, paid API assumptions beyond configured ThetaData, or LLM trade decisions. The immediate goal is proving or rejecting the strategy with point-in-time multi-year data, realistic slippage/fees, and a locked OOS protocol.

Before implementing, inspect git status, list open PRs, and verify whether PR #96 and PR #97 have merged. If they are still open, treat them as current context and avoid duplicating or conflicting with them.
```
