# Decision/Handoff: claude/financial-events Branch Status

- **Date:** 2026-05-18
- **Owner:** the maintainer (Claude as scribe)
- **Branch:** `claude/financial-events` (off `proposal/financial-pipeline`)
- **Status:** ready for draft-PR review by Codex and Jonathan

## What landed on this branch

Four commits:

1. `docs: workflow alignment + rename brain/12 -> brain/13`
2. `A: Fed RSS -> Event normalization`
3. `B: extend Event normalization to all five news adapters`
4. `C: event-window research harness`

(Plus this handoff note.)

## How we agreed to collaborate (active rules)

Per `brain/12_branch_collaboration_workflow.md` (Codex) + `brain/14_agent_workflow_amendment.md` (Claude):

- Codex writes to `codex/*`, Claude writes to `claude/*`.
- `main` and `proposal/*` are read-only for agents unless Jonathan explicitly approves.
- Build on someone else's branch by creating a child branch off it.
- **Jonathan is the sole human merger to `main`.** Agents may open PRs, comment, and approve, but never click the merge button.
- Default to draft PRs after agent pushes (`gh pr create --draft`).
- `brain/NN` numbering is sticky. When two branches collide on a number, the more foundational doc wins; the other yields to a higher number.
- **Every commit gets a `TL;DR:` line near the top.** One sentence, ≤120 chars, plain English. Branches get a TL;DR in the PR body too. Format documented in `brain/14`.

## How to start a new Claude session safely

Before doing anything else:

```bash
cd $REPO
git fetch origin --prune
git log --oneline --graph --decorate --all -30
```

Look for new branches from `codex/*` or `proposal/*`. **Read them before writing**, especially:
- Anything new on `codex/collaboration-workflow` (the workflow + AGENTS.md/CLAUDE.md).
- Anything new on `proposal/financial-pipeline` (the integration line).
- Anything new on `main` (Jonathan's merges).

If Codex pushed a new branch since the last session, branch off the right base before writing.

## What's open / unfinished

- **D: wire `AlpacaBroker` into the runner** — explicitly skipped per `brain/02_trading_intelligence_plan.md` phase ordering (paper trading comes AFTER event-window research validates signals have edge). Track as future branch `claude/alpaca-broker-wiring`.
- **First real event-window study run.** The harness in C is built and tested; we haven't actually run it yet (needs Alpaca keys + accumulated `news_events` rows from a few daily runs).
- **FinBERT sentiment classifier.** `brain/05` lists FinBERT; not in this branch. Future: `claude/finbert-sentiment` adding a `signals/sentiment_finbert.py` that populates `Event.sentiment_score` via `model_outputs` with audit trail per `brain/10`.
- **Apify X scraper.** Listed in `brain/03`; not in this branch. Future.
- **`sec-edgar-downloader` swap.** `brain/03` prefers that lib over our hand-rolled SEC EDGAR Atom parser. Cheap follow-up.
- **`pgvector` evidence store.** `brain/05` plans Postgres+pgvector for v1. We're still on SQLite. Out of scope until we have enough events to need vector search.
- **Numbering collision** — once `codex/collaboration-workflow` merges to main, my `brain/12` rename to `brain/13` and new `brain/14` need to be sanity-checked to make sure no other branch claimed those numbers.

## Other ways to collaborate before merging (reminders)

Beyond branch pushes:

- **Draft PRs** (`gh pr create --draft`) — line-level comments, no merge pressure.
- **GitHub issues** — pre-implementation alignment ("I plan to do X, thoughts?").
- **PR review comments** — once Jonathan opens a PR from `codex/collaboration-workflow` -> main, leave a +1 review with our amendments noted.
- **Branch off someone else's WIP** to push a suggestion — e.g. `claude/<task>-on-codex-<task>` if we want to extend something Codex pushed.

## Specific things Codex / Jonathan should know

- The `news_events` table is named with a `news_` prefix to avoid colliding with the pre-existing system event log named `events`. The `Event` pydantic class still matches `brain/08` exactly; only the SQL table name differs.
- `brain/12` was yielded to Codex's `brain/12_branch_collaboration_workflow.md`. Mine moved to `brain/13_financial_pipeline_proposal.md`.
- `SingleLLMCallBrain` is still NOT in this codebase, per `brain/10`. Don't add it.
- `pyproject.toml`'s `pandas` pin was loosened (3.0.3 -> >=2.2,<3.0) because pandas 3.0 has not shipped. Flagged for Jonathan to confirm before merging.

## Test count

132 tests, all passing. `ruff check` and `ruff format` clean.

## Final action this session

Push `claude/financial-events` and open a draft PR targeting `proposal/financial-pipeline` (per the workflow amendment).
