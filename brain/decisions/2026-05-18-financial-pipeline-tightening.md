# Decision: Financial Pipeline Tightening Pass

- **Date:** 2026-05-18
- **Branch:** `proposal/financial-pipeline`
- **Status:** applied

## Context

Review of the financial pipeline branch found three merge-blocking gaps:

- `trader-daily schedule` was documented but crashed because `trader.scheduler` did not exist.
- LLM calls returned prompt/cost metadata but the runner did not persist it to `llm_calls`.
- The runner set `equity_session_start` equal to current equity, so the daily loss gate could not catch drawdowns from the prior recorded equity.

Jonathan also chose to keep the `Brain` naming.

## Decision

Keep `Brain` as the project term for a decision module, but clarify in code that a Brain can be deterministic, LLM-assisted, or a baseline and still remains downstream of risk gates.

Add:

- a real daily scheduler module
- LLM audit metadata fields on `Decision`
- runner persistence into `llm_calls`
- latest-equity lookup in `Store`
- runner risk checks against prior recorded equity when available
- tests for each behavior

## Consequences

The branch is safer to review and closer to mergeable. It is still a proposal: the next architectural step remains adapter output -> normalized `Event` records -> event-window research before any paper-trading pilot.
