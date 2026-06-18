# Branch Collaboration Workflow

This repo is shared by humans and coding agents. The safest workflow is to read each other's branches constantly, but write only to owned branches.

## Core Rule

Fetch and inspect everything. Push only to your own branch.

That means Codex can read Claude work and Claude can read Codex work, but each agent creates a child branch before editing.

## Standard Branch Stack

```text
main
  proposal/financial-pipeline
    codex/financial-pipeline-tightening
    claude/financial-pipeline-runner
  codex/collaboration-workflow
```

`main` should stay stable. Proposal branches can hold larger ideas. Agent branches should contain specific changes that can be reviewed and merged.

## Daily Collaboration Loop

```bash
git fetch origin --prune
git status --short --branch
git log --oneline --graph --decorate --all -30
```

Review another branch:

```bash
git diff origin/main...origin/proposal/financial-pipeline
```

Build on another branch:

```bash
git switch -c codex/<task> origin/proposal/financial-pipeline
```

or:

```bash
git switch -c claude/<task> origin/codex/<branch>
```

Push only the new branch:

```bash
git push -u origin <new-branch>
```

## Merge Direction

Use PRs instead of direct pushes:

- child branch into proposal branch when the proposal is still evolving
- proposal branch into `main` when the proposal is clean and accepted
- small feature or fix branch directly into `main` when it is self-contained

## Agent Files

- `AGENTS.md` gives shared instructions to coding agents.
- `CLAUDE.md` gives Claude Code-specific startup and branch rules.
- `CONTRIBUTING.md` gives the human-facing workflow.
- `.github/pull_request_template.md` makes branch ownership and verification visible in every PR.

## What Happened On 2026-05-18

Codex accidentally pushed a tightening commit directly to `proposal/financial-pipeline`. The work was preserved on `codex/financial-pipeline-tightening` so it can be reviewed separately. Going forward, agents should create child branches before editing proposal branches unless the maintainer explicitly approves direct shared-branch work.
