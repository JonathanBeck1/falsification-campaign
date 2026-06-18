# Financial Pipeline Proposal

> **Status:** discussion branch — `proposal/financial-pipeline`. Not for merge yet.
> **Author:** the maintainer (with Claude as scribe).

## Purpose

This branch ports a self-contained trading pipeline that was built
locally into the `src/trader/` skeleton, fitting the architecture
(`brain/01_system_architecture.md`) and the LLM boundaries
(`brain/10_llm_agent_boundaries.md`).

## What landed (mapped to your layers)

| Your layer | What this branch adds | Notes |
|---|---|---|
| `adapters/news/finnhub.py` | Finnhub company-news REST | free tier, 60 req/min |
| `adapters/news/yahoo.py` | Yahoo Finance news via `yfinance`, with `merge_news()` dedup | no auth, fragile endpoint, graceful failure |
| `adapters/alpaca/news.py` | Alpaca News REST (Benzinga-sourced) | works on the free Alpaca data tier |
| `adapters/alpaca/market.py` | Alpaca daily OHLCV bars via `alpaca-py` | |
| `adapters/sec/edgar.py` | SEC EDGAR 8-K Atom feed per ticker (hardcoded CIK map) | per `brain/03`, your preferred lib is `sec-edgar-downloader` — happy to swap |
| `adapters/macro/fed.py` | Federal Reserve monetary-policy RSS | stdlib XML, no new deps |
| `adapters/macro/fred.py` | FRED via `fredapi` | VIX, yield curve 10y-2y, fed funds, CPI YoY, unemployment |
| `normalization/models.py` | Pydantic models for `Event`, `Entity`, `EvidenceSnippet`, `ModelOutputMeta` | **exactly your schema from `brain/08`** |
| `storage/snapshot.py` | All-in-one daily container (`DailySnapshot`) | **v0 scaffold; will be replaced by Event records** — flagged |
| `storage/store.py` + `schema.sql` | SQLite store: snapshots, signals (decisions), orders, fills, per-signal virtual portfolios, equity curves, LLM calls, events | |
| `signals/classical.py` | Pure-rule SMA-200 + RSI + VIX + yield-curve signal | no LLM |
| `signals/hybrid.py` | LLM extracts structured features (regime sentiment, event severity, Fed-day) → deterministic rule decides | matches `brain/10` exactly |
| `signals/base.py` | `Brain` protocol + `Decision` record | `Brain` naming is local — open to renaming to `SignalGenerator` |
| `backtesting/baselines/buy_and_hold.py` | Always-long control baseline | for replay studies, not as a daily signal |
| `execution/risk.py` | Hard-coded risk gate: kill switch, daily loss cap, position cap, PDT, LLM cost cap | sits between signals and orders |
| `execution/broker.py` | `SimBroker` (per-signal virtual portfolio) + `AlpacaBroker` (real paper orders, idempotent `client_order_id`) | |
| `llm/client.py` | LiteLLM wrapper, prompt-hash logging, cost tracking | one client interface across providers |
| `notify/discord.py` | Discord webhook notifier | best-effort, never breaks the loop |
| `runner.py` | **Temporary** all-in-one daily orchestrator: fetch → signals → risk → simulated fill → log → notify | flagged for split into `ingestion/` + `signals/` + `execution/` per your architecture |
| `scripts/run_daily.py` | Operator entrypoint | |
| `tests/financial/*` | 85 pytest tests, all mocked, no network | |

## What I dropped from my local build

Out of respect for your `brain/10_llm_agent_boundaries.md`:

- **`SingleLLMCallBrain`** — a single LLM call deciding BUY/SELL/HOLD violates
  "LLMs do not place trades." Dropped from this branch entirely.
- **`MetaBrain` ensemble re-weighter** — was on a planning doc only; doesn't fit
  the deterministic-signal model and assumes voting between deciders, which is
  the wrong shape for this architecture. Dropped.

## Things I changed in your existing files

Minimal, but worth calling out so you can veto:

1. **`pyproject.toml`** — I loosened `pandas==3.0.3` to `pandas>=2.2,<3.0`.
   This keeps the trading stack on the pandas 2.x line used by current
   dependencies while the pandas 3.x ecosystem shakes out. Also added a
   `[trading]` extra to keep the alpaca-py / litellm / etc. dependencies
   opt-in.
2. **`README.md`** — appended a "Financial Track" section. No changes above it.

I did **not** modify:
- Any `brain/00`–`brain/11` doc
- `brain/decisions/2026-05-18-initial-repo-structure.md`
- `src/trader/__init__.py`
- `configs/sources.example.toml`
- `docs/superpowers/*`
- `research/trading-repos/*`
- `requirements.txt`
- `.gitignore`

## How I tried to follow your protocol

- **Branch naming:** `proposal/financial-pipeline`. Doesn't match the `feature/...`
  convention because the intent was "obviously temp." Easy to rename.
- **Decision doc:** added `brain/decisions/2026-05-18-trading-stack-handoff.md`
  per `brain/11`.
- **No secrets, cookies, profiles in git.** `.env.example` only.
- **Tests around parsing + schema conversion.** Adapter tests are heavy on this.

## What still needs your input before this can merge

1. **Brain/signal naming.** Resolved for now: keep `ClassicalBrain` / `HybridBrain`. `Brain` now has an explicit protocol docstring clarifying that it means decision module, not unchecked AI authority.
2. **Test framework.** The existing tests use `unittest`. I used pytest because (a) it runs unittest tests too, (b) our 85 tests are pytest. Happy to convert if you prefer one framework.
3. **`sec-edgar-downloader` vs my hand-rolled SEC.** `brain/03` says you prefer the downloader. Mine works today; happy to swap if you want vendor consistency.
4. **`pgvector` vs SQLite for evidence store.** You said `pgvector` for v1 in `brain/05`. I left storage as SQLite for now since this branch doesn't introduce an evidence store yet — just the snapshot container. Splitting raw evidence + Postgres+pgvector is the next architectural step.
5. **Vectorbt for backtesting.** `brain/05` lists it as preferred. I didn't ship a backtest harness in this branch — `backtesting/` has only the baseline. Next branch.
6. **Apify X scraper.** `brain/02`, `brain/03` mention this. Not in this branch.
7. **Sentiment classification (FinBERT / VADER).** `brain/05` lists these. Not in this branch — `HybridBrain` uses Claude Haiku for now. Easy to add as a `signals/sentiment_finbert.py` later.

## My take on next steps in priority order

1. You review this branch, push back on naming + structure.
2. We agree on the event-store boundary: when does data leave `storage/` as a
   `NewsItem`-shaped container vs. a normalized `Event`? Probably the next branch.
3. Build the **first event-window study** from `brain/09` against the news we
   already have wired (Fed-day SPY/QQQ reaction is the natural one).
4. Then — and only then — consider the `signals/` brains as candidates for a
   paper-trade pilot.

## A few honest things to disagree about

- Your `00_project_north_star.md` reads "What good looks like" as a fully
  auditable evidence chain. Our v0 snapshot.py is **not that yet** — it's
  basically a bundle of raw adapter outputs plus computed indicators. The
  `normalization/` skeleton is the bridge but currently no adapter produces
  `Event` records. Honest gap to flag.
- I'm skeptical the "evidence has trading edge after fees+slippage" hypothesis
  is right for daily-cadence SPY/QQQ specifically — most of the academic
  evidence on LLM trading agents collapses out-of-sample. The right first
  study is `brain/09`'s event-window test (15m/1h/1d reaction after a Fed
  release). That's a research result, not a trading system. Worth aligning
  on whether we're building a research platform first vs a trading bot first.

If you want changes, drop comments on the branch and I'll iterate.
