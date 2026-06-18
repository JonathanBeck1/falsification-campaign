# Decision: Trading-Pipeline Handoff Onto `src/trader/`

- **Date:** 2026-05-18
- **Owner:** the maintainer
- **Branch:** `proposal/financial-pipeline`
- **Status:** proposed, awaiting Jonathan's review

## Context

A self-contained daily trading agent had been built locally (Python 3.11,
Alpaca paper, 5 news adapters, risk gate, SimBroker, classical + hybrid
signal generators, now tightened to 85 tests). Jonathan, in parallel, created this repo
with a `src/trader/` skeleton and 11 `brain/` docs articulating a
data-first / evidence-first architecture and explicit LLM boundaries.

The two efforts overlap heavily but speak at different levels: the existing
work is the trade-engine side, Jonathan's is the evidence-pipeline side.
They stack rather than compete.

## Decision

Port the existing modules into `src/trader/` under Jonathan's layout, with three
hard rules:

1. Don't touch any of Jonathan's existing files (brain/00–11,
   research/, configs/, docs/superpowers/, his `requirements.txt`).
2. Drop modules that violate `brain/10_llm_agent_boundaries.md`
   (specifically: `SingleLLMCallBrain`).
3. Use Jonathan's package names everywhere
   (`stock_trader` → `trader`, `brains` → `signals`, `STOCK_TRADER_` → `TRADER_`).

Land everything on `proposal/financial-pipeline` for review, not on `main`.

## Consequences

**Good:**
- We have one unified trading repo.
- The working risk gate, SimBroker, adapters, and signals are immediately
  usable.
- Pydantic `Event` schema is now defined (per `brain/08`) so the next branch
  can wire adapters → Events.

**Costs / trade-offs:**
- We gained ~12 new dependencies (alpaca-py, litellm, anthropic, fredapi,
  finnhub-python, etc.) — gated behind a `[trading]` extra so contributors
  who don't need them aren't forced to install them.
- `pyproject.toml`'s `pandas==3.0.3` pin was loosened to `>=2.2,<3.0` to keep
  the trading stack on the pandas 2.x line used by current dependencies while
  pandas 3.x compatibility shakes out. Flagged for Jonathan to approve.
- `storage/snapshot.py` (`DailySnapshot`) is a v0 all-in-one container; it
  will be replaced by Event records once the normalization layer is wired.
  Explicitly flagged in the proposal doc.
- `runner.py` is a temporary all-in-one orchestrator; needs to be split into
  `ingestion/` + `signals/` + `execution/` per Jonathan's architecture in a
  follow-up branch.

## Follow-ups (next branches)

1. `feature/event-normalization` — first adapter → `Event` flow, starting with
   Fed RSS releases (highest-signal, lowest entity-ambiguity).
2. `research/fed-day-event-window` — first event-window study from `brain/09`:
   does a Fed press release move SPY/QQQ at 15m / 1h / 1d horizons?
3. `feature/evidence-store-postgres` — split raw evidence into Postgres +
   `pgvector` once we know the access patterns.
4. `feature/sec-edgar-downloader-swap` — replace the hand-rolled SEC Atom
   parser with `sec-edgar-downloader` per `brain/03`.
