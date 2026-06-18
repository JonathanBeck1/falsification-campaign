# Decision: Adopt Codex's Branch Workflow, Add Sole-Merger Rule

- **Date:** 2026-05-18
- **Owner:** the maintainer (Claude as scribe)
- **Branch:** `claude/financial-events`
- **Status:** proposed; awaiting Jonathan's acceptance

## Context

Codex pushed `codex/collaboration-workflow` defining a branch-ownership convention (Codex → `codex/*`, Claude → `claude/*`, main is PR-only, proposal/* are read-only for agents). Two issues to resolve before the Claude side proceeds:

1. Both `codex/collaboration-workflow` and `proposal/financial-pipeline` reserved `brain/12_*.md` for different docs — a collision waiting to happen on merge.
2. With two agents both able to push to `main` as collaborators, there's no clear chokepoint to prevent merge collisions when work happens in parallel.

## Decision

1. **Adopt Codex's `brain/12_branch_collaboration_workflow.md` workflow as-is.**
2. **Yield `brain/12` to Codex.** Rename Claude's doc from `brain/12_financial_pipeline_proposal.md` → `brain/13_financial_pipeline_proposal.md`. Update references in `README.md` and `src/trader/normalization/models.py`.
3. **Add a sole-merger rule.** Only Jonathan clicks the merge button on PRs to `main`. Agents may open, review, and approve PRs but never merge to main themselves.
4. **Establish numbering yields-to-foundational rule.** When two branches claim the same `brain/NN`, the more foundational doc keeps the lower number.
5. **Default to draft PRs for agent-pushed branches.** `gh pr create --draft` after every agent push, against `proposal/<theme>` or `main` as appropriate.

These additions are written up in `brain/14_agent_workflow_amendment.md`.

## Consequences

**Good:**
- Both agents have a clear, predictable place to write code (`codex/*` vs `claude/*`).
- `main` is protected by a single human decision-maker.
- Brain numbering stays consistent across branches once merged.
- Draft PRs give Codex, Claude, and Jonathan a place to comment at the diff level before anything lands.

**Costs / trade-offs:**
- Slight overhead per agent task: must create a child branch + open a draft PR before review.
- Jonathan becomes a soft bottleneck on merges. Acceptable at the current scale; would need delegation if the team grows.
- Numbering yield rule is a judgment call. We're using "foundational > project-specific" — could need refinement.

## Follow-ups

- Set up branch protection on `main` in GitHub settings: require PR + 1 approval, no direct pushes, no force-pushes.
- If Jonathan accepts the sole-merger rule, also consider adding a CODEOWNERS file to auto-request his review.
- Update `AGENTS.md` / `CLAUDE.md` (currently on `codex/collaboration-workflow`) to reference this amendment when both branches merge.
