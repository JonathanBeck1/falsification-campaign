# Agent Workflow Amendment

> **Read this together with `brain/12_branch_collaboration_workflow.md`**
> (currently on `codex/collaboration-workflow`).
> This doc is an amendment from the Claude side, written on
> `claude/financial-events`. The maintainer integrates both into the canonical
> docs on `main` when the two source branches merge.

## What we agree with from `brain/12` (Codex's draft)

- **Fetch and inspect everything. Push only to your own branch.**
- Codex → `codex/*`, Claude → `claude/*`, `main` is PR-only.
- `proposal/*` branches are read-only for agents unless the maintainer explicitly approves direct pushes.
- Build on someone else's work by creating a child branch.
- PR direction: child → proposal while proposal evolves; proposal → main when accepted.

These rules are adopted as-is.

## What this amendment adds

### 1. The maintainer is the sole human merger to `main`

Neither agent should merge to `main`, even if both are co-owners and have permission. The intent is to prevent merge collisions between agents working in parallel.

Agents may:
- Open PRs against `main`
- Approve PRs (as collaborators)
- Comment on other PRs

Only the maintainer does the final merge button click. This becomes the audit chokepoint.

### 2. `brain/` numbering is sticky AND yields to foundational docs

When two branches both claim the same `brain/NN_*.md` number, the more foundational doc wins the lower number. Foundational means: shared protocol / infrastructure / cross-cutting rules. Project-specific or track-specific docs yield to higher numbers.

Applied today: `brain/12_branch_collaboration_workflow.md` (Codex) is more foundational than `brain/12_financial_pipeline_proposal.md` (Claude). Claude's doc has been renamed to `brain/13_financial_pipeline_proposal.md` on this branch.

Once both source branches merge, the layout will be:

```text
brain/
  00_project_north_star.md         (maintainer, on main)
  01_system_architecture.md        (maintainer, on main)
  …
  11_collaboration_protocol.md     (maintainer, on main)
  12_branch_collaboration_workflow.md  (from codex/collaboration-workflow)
  13_financial_pipeline_proposal.md    (from proposal/financial-pipeline, renamed)
  14_agent_workflow_amendment.md       (from claude/financial-events — this doc)
```

### 3. Draft PRs as the default pre-merge review channel

Once a `claude/<task>` or `codex/<task>` branch is pushed, the author opens a **draft** PR (`gh pr create --draft`) targeting either `proposal/<theme>` or `main` depending on scope. The draft state signals "ready for diff-level discussion, not for merge."

Draft PRs let either agent (and the maintainer) leave line-level comments and request changes. The draft is converted to a regular PR only when both agents and the maintainer are aligned.

### 4. Numbering conflicts: notify, don't overwrite

If an agent discovers that the `brain/NN_*` number it intended is already taken on another branch, **rename your own doc**, do not edit the other branch's file. Use this doc (or a new amendment doc) to note the rename so future readers can find the file.

### 5. Every commit gets a TL;DR

Commit messages on agent branches MUST include a single-line `TL;DR:` near the top so the branch is scannable in `git log --oneline` and PR reviews. Format:

```text
<conventional prefix>: <subject line, ≤ 70 chars>

TL;DR: <one sentence, ≤ 120 chars; what changed and why, plain English>

[longer body — what / why / how tested / assumptions / follow-up]

Co-Authored-By: <agent line if applicable>
```

The TL;DR is the *one* line a reviewer should be able to remember about the commit a week later. Don't pad it with implementation details — those belong in the body.

Branches themselves should also have a TL;DR in their PR description and in any handoff doc filed under `brain/decisions/`. Same format, same intent.

### 6. This doc itself is amendable

If the maintainer or Codex disagrees with anything here, push a follow-up amendment doc (e.g. `brain/15_agent_workflow_amendment_v2.md`) rather than editing this one. The amendment chain stays auditable.

## What still needs the maintainer's sign-off

- The "maintainer is sole merger" rule. Easy to revert to delegate merge rights.
- The brain/13 rename (technically reversible by another rename).
- The draft-PR-as-default convention (currently informal; could be enforced via branch protection rules later).
