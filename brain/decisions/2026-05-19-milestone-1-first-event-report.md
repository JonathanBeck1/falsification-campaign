---
title: Milestone 1 — first event-window report and what it exposed
date: 2026-05-19
status: draft (review pending)
owner: the maintainer (claude assist)
---

# Milestone 1 — First Event-Window Report

Status: **partial.** Pipeline runs end-to-end, but only one source produced events. The first real Fed/SPY study from `brain/16_edge_proof_mvp_build_plan.md` Task 3 cannot run yet against current data — see "Gaps" below.

## What was done

1. Synced `$REPO` to `origin/main` (965e087 — "feat: classify yahoo market events").
2. Refreshed venv and installed `.[dev,trading]`.
3. Ran the full suite: **153 passed, 1 warning** (`websockets.legacy` upstream — non-actionable).
4. Created local `.env` (gitignored). Configured: `TRADER_LIVE=false`, `TRADER_TICKER=SPY`, `TRADER_CONTEXT_TICKERS=SPY,QQQ`, `TRADER_SEC_USER_AGENT=trader you@example.com`. **No Alpaca / Finnhub / FRED / LLM keys set yet.**
5. Ran `trader-daily fetch-events`. Result:

   | source | persisted |
   |---|---|
   | yahoo_news | 14 |
   | fed | **0** |
   | finnhub | 0 (no key) |
   | alpaca_news | 0 (no key) |
   | sec_edgar | 0 (no `TRADER_SEC_TICKERS` configured) |

6. Ran `trader-daily research-events --benchmark SPY --source yahoo_finance --output output/reports/yahoo-spy-first-run.md`. Report written, 79 SPY 5m bars fetched via free Yahoo path.

## What the data showed

Honest read: nothing actionable.

- 14 Yahoo events, all from a single intraday window on 2026-05-19. No multi-day coverage, no event repetition.
- Largest cell N = 8 ("other"); smallest cells N = 1. Anything with N ≤ 3 is noise.
- The single `fed_commentary` row (N=1, +0.56% at 1h, +0.12% at 5m) is a **Yahoo article classified as Fed**, not an actual FOMC release — sanity-check whether PR #9's classifier should be that liberal with the `fed_commentary` label.
- 4h horizon is missing or partial for most event types because the market simply hasn't moved 4h forward from the events yet.

## Gaps exposed by this run

These should drive the next claude/* or codex/* tasks:

1. **`fetch-events` has no historical backfill.** `fetch_fed_press` is called with `lookback_days=14` (hardcoded in `src/trader/runner.py`). The most recent FOMC item is from 2026-01-28 (>14 days ago), so the DB has zero Fed events — the very source the MVP plan calls out as the first target. **Fix candidates**: add a `--lookback-days` CLI flag to `fetch-events`, OR a separate `backfill-events --source fed --since 2025-01-01` command. Recommend a flag, since most adapters already accept a `lookback_days` arg.
2. **No SEC events.** `TRADER_SEC_TICKERS` is empty in the new `.env`. Either populate it with the default list from `.env.example` (AAPL, MSFT, NVDA, etc.) or decide that the first study should not include single-name 8-K analysis.
3. **No Alpaca News, no Finnhub.** Both require keys. Adding them roughly doubles or triples the event diversity. Low-effort lift; needed before any real edge claim.
4. **Yahoo event classifier may be too liberal with `fed_commentary`.** Worth a follow-up brain/decisions note or a tightening PR.
5. **Yahoo news has no point-in-time semantics.** The PR #8/#9 modules note this in their docstrings — `yfinance` returns "what's on the page now," not historical news. This means Yahoo events can't be backtested honestly. Milestone 2 (`observed_at` / `ingested_at` discipline) will need to flag or reject Yahoo for any back-study.

## Recommended next work

In priority order:

1. **Add `--lookback-days` to `fetch-events`.** Smallest unlock; lets a single run pull months of Fed releases. Good `claude/*` task — narrow, testable, doesn't collide with Jonathan's dashboard PR #10.
2. **Get Alpaca paper + Finnhub keys into `.env`.** Cheap; multiplies useful events.
3. **First *real* Fed/SPY study** after #1 — re-run Task 3 from the MVP plan against ≥6 months of Fed events.
4. **Spec the Yahoo classifier scope tightening.** Open a discussion brain doc; don't change behavior without Jonathan's signoff.

## Decision

- **Do not commit** the SQLite database (`data/trader.sqlite`) or `output/reports/yahoo-spy-first-run.md`. Both are local-only per `.gitignore`.
- **Do commit** this decision note as the artifact of the run.
- **Do not** declare Milestone 1 done. It's blocked on either a historical Fed source or a backfill mechanism — capturing that explicitly so we don't move on prematurely.
