# Edge-Proof MVP Build Plan

> Status as of 2026-05-19: the financial pipeline foundation is on `main`, event-only ingestion is on `main`, and this document is the operating plan for proving or rejecting edge before live trading.

## Goal

Build the smallest serious research system that can prove or reject news/event trading edge before any live execution.

The point is not to build a flashy trading bot. The point is to build an evidence machine:

1. Ingest events.
2. Normalize them into deterministic, auditable records.
3. Measure forward returns honestly.
4. Promote only repeatable signals into alerts.
5. Permit paper/live execution only after an explicit edge gate.

## Non-Negotiables

- No live trading until the edge gate is passed and the maintainer explicitly approves it.
- No autonomous LLM order decisions. LLMs may extract features and summarize evidence; deterministic rules decide whether anything becomes a candidate.
- No `.env`, secrets, cookies, browser profiles, paid exports, raw scrape dumps, or local SQLite databases in git.
- Use TDD for behavior changes: write failing test, verify red, implement, verify green.
- Use `codex/*` branches for Codex work and `claude/*` branches for Claude Code work.
- Open draft PRs by default.
- The maintainer is the only person who merges into `main`.
- Do not copy code from FinceptTerminal. It is reference-only because of AGPL/commercial-license risk.

## Current Main-State

Merged:

- PR #4: deterministic event IDs and source fetch isolation.
- PR #6: financial pipeline foundation.
- PR #7: safe event-only ingestion command and event-window report metadata.

`main` now contains:

- Source adapters: Alpaca News, Finnhub, Yahoo, SEC EDGAR, Fed RSS, FRED, Alpaca bars.
- Normalized `Event` schema and source-specific normalizers.
- SQLite storage for snapshots, decisions, orders, fills, system events, and `news_events`.
- `trader-daily fetch-events` for event-only collection.
- `trader-daily research-events` for event-window forward-return reports.
- Simulated broker, risk gate, classical signal, hybrid LLM-feature signal, and daily runner.
- Collaboration docs in `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, and `brain/12_branch_collaboration_workflow.md`.

## Verification Standard

Run this before every PR:

```bash
git diff --check
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/trader tests/financial
```

Current expected result after PR #7:

```text
144 passed, 1 warning
All checks passed!
```

The warning is from `websockets.legacy` via the Alpaca dependency and is not currently actionable inside this repo.

## Current Architecture

```text
adapters/*              fetch raw source data
storage/snapshot.py     provider-neutral NewsItem and bar models
normalization/*         NewsItem -> Event conversion
ingestion/events.py     event-only fetch/normalize/persist flow
storage/store.py        SQLite persistence
backtesting/*           event-window and baseline research
signals/*               deterministic and LLM-feature signal experiments
execution/*             risk gate and simulated/paper broker boundary
cli.py                  operator commands
brain/*                 durable strategy, architecture, and decision memory
```

Data flow:

```text
source adapters
  -> NewsItem batches
  -> source-specific normalizers
  -> Event rows in SQLite
  -> event-window research
  -> candidate scoring
  -> alert-only paper watch
  -> explicit edge gate
  -> paper trading
  -> live trading only by approval
```

## Commands

Install locally:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,trading]"
```

Fetch and persist normalized events only:

```bash
trader-daily fetch-events
```

Run event-window research from stored events:

```bash
trader-daily research-events \
  --benchmark SPY \
  --source federalreserve.gov \
  --event-type fed_commentary \
  --output output/reports/fed-spy-first-run.md
```

Run daily paper/simulated brains:

```bash
trader-daily run-once
```

That command remains research/paper oriented by default. Keep `TRADER_LIVE=false`.

## Milestone 0: Foundation

Status: done.

- [x] Establish repo docs and collaboration workflow.
- [x] Land financial source adapters and storage foundation.
- [x] Normalize Fed, Finnhub, Yahoo, Alpaca News, and SEC items into `Event`.
- [x] Add deterministic `event_id`.
- [x] Isolate source fetch failures so one broken provider does not kill a run.
- [x] Add event-window research harness.
- [x] Add safe event-only ingestion module.
- [x] Add `trader-daily fetch-events`.
- [x] Add run metadata to event-window reports.

## Milestone 1: First Real Event Study

Purpose: produce the first honest local report using real data and no trading.

### Task 1: Configure Local `.env`

Create `.env` from `.env.example` locally. Do not commit it.

Required values:

```text
TRADER_LIVE=false
TRADER_TICKER=SPY
TRADER_CONTEXT_TICKERS=SPY,QQQ
TRADER_SEC_TICKERS=
TRADER_SEC_USER_AGENT=<maintainer-controlled contact email>
ALPACA_PAPER_KEY_ID=<local paper key>
ALPACA_PAPER_SECRET_KEY=<local paper secret>
```

Optional for more sources:

```text
FINNHUB_API_KEY=<local key>
FRED_API_KEY=<local key>
```

Expected:

- `.env` stays untracked.
- `git status --short` does not show secrets.

### Task 2: Fetch Events

Run:

```bash
trader-daily fetch-events
```

Expected:

- Command prints per-source counts.
- `data/trader.sqlite` exists locally and remains untracked.
- `news_events` has at least Fed events if Fed RSS is reachable.

Useful inspection:

```bash
sqlite3 data/trader.sqlite \
  "select source, event_type, count(*) from news_events group by source, event_type order by source, event_type;"
```

### Task 3: Produce First Fed/SPY Report

Run:

```bash
trader-daily research-events \
  --benchmark SPY \
  --source federalreserve.gov \
  --event-type fed_commentary \
  --output output/reports/fed-spy-first-run.md
```

Expected:

- Report includes a `Run Metadata` block.
- Report includes event counts, bar counts, source, event type, and bar interval.
- Report is local output only and stays untracked.

### Task 4: Write A Decision Note

Create a dated note in `brain/decisions/` summarizing:

- What data was collected.
- How many events were available.
- Whether forward-return rows had enough N to matter.
- Whether the next step should be more data collection, source expansion, or candidate scoring.

Commit the decision note only. Do not commit the report file or SQLite database.

## Milestone 2: Data Quality And Point-In-Time Discipline

Purpose: make the research results harder to fool.

Tasks:

- Add an ingestion run table with `run_id`, source counts, started/finished timestamps, and error counts.
- Store `observed_at` and `ingested_at` for every event and make reports use point-in-time filters.
- Add stale-news detection: reject or flag events whose `published_at` is older than the configured freshness window at ingestion time.
- Add duplicate/near-duplicate checks across source adapters.
- Add report filters for `observed_at` and `ingested_at`, not just `published_at`.
- Add tests proving the report cannot use events that were not observed by the backtest cutoff.

Definition of done:

- A report can state exactly which run produced the events it studied.
- Every event row answers: when was it published, when did we observe it, and when did we ingest it?
- Tests cover stale article rejection and point-in-time filtering.

## Milestone 3: Candidate Scoring, Alert-Only

Purpose: convert event evidence into watchlist candidates without orders.

Start with deterministic candidate scoring, not LLM judgment.

Candidate fields:

- `candidate_id`
- `event_id`
- `ticker`
- `direction`
- `horizon`
- `confidence`
- `reason`
- `features_json`
- `created_at`
- `expires_at`

Initial candidate types:

- Fed commentary -> SPY/QQQ volatility watch.
- 8-K material event -> affected ticker watch.
- Earnings or guidance headline -> affected ticker watch.
- FDA/regulatory headline -> affected ticker watch.

Tasks:

- Add candidate model and SQLite table.
- Add `trader-daily score-events` command.
- Add tests proving candidate scoring does not place orders.
- Add ntfy or Discord alert-only output for high-confidence candidates.

Definition of done:

- Candidates can be generated and alerted without touching broker code.
- Every candidate is traceable back to one or more `Event` evidence rows.

## Milestone 4: Honest Backtesting

Purpose: decide whether any event class is worth paper trading.

Tasks:

- Build walk-forward splits by time, not random split.
- Add transaction cost and slippage assumptions to event reports.
- Track sample size, hit rate, mean/median return, t-stat, drawdown, and confidence interval.
- Add deflated Sharpe or similar multiple-testing warning once there are enough candidate strategies.
- Add benchmark comparisons against buy-and-hold and no-trade baselines.

Minimum gate for "interesting":

- At least 100 independent candidate observations for a narrow strategy, or a clearly documented reason if fewer.
- Positive out-of-sample performance after costs.
- No obvious leakage from future data.
- Stable behavior across at least two non-overlapping time windows.

## Milestone 5: Paper Alerts To Paper Trading

Purpose: only after backtests look non-ridiculous, allow simulated/paper orders.

Tasks:

- Add a paper-only event strategy that consumes candidates.
- Keep hard risk gates: max daily loss, max position concentration, kill switch, PDT awareness, LLM cost cap.
- Add alerting for fills, drawdowns, rejected trades, and halted symbols.
- Add a manual approval flag before any candidate class can route to paper orders.

Definition of done:

- Strategy can run paper-only for at least 20 market days.
- Every order is tied to candidate ID, event ID, and strategy version.
- Failures are visible in alerts and stored system events.

## Milestone 6: Edge Gate

Live trading is allowed only if the maintainer explicitly approves after reviewing:

- Backtest methodology.
- Out-of-sample results.
- Paper-trading results.
- Slippage assumptions.
- Drawdown behavior.
- Known failure modes.
- Minimum capital and PDT constraints.

Kill criteria:

- No signal survives out-of-sample testing after costs.
- Candidate logic only works on one cherry-picked date range.
- Results are driven by stale-news trades.
- LLM-derived features are not reproducible or auditable.
- Paper results diverge materially from backtest assumptions.

If the kill criteria trigger, pivot the codebase toward the SaaS fallback: research dashboards, signal explainability, alerting, and event intelligence for retail users.

## Next Immediate Work

The next practical work item is Milestone 1:

1. Configure local `.env` without committing it.
2. Run `trader-daily fetch-events`.
3. Run the first Fed/SPY event-window report.
4. Write the first `brain/decisions/` note from the result.

This is the fastest way to learn whether the pipeline is collecting useful evidence or just clean-looking noise.
