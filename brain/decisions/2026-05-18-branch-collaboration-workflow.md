# Decision: Use Owned Agent Branches

## Date

2026-05-18

## Context

Jonathan is using Codex while a collaborator is using Claude Code. Both agents need to read and build on each other's commits without corrupting shared work or pushing directly to the wrong branch.

## Decision

Adopt owned agent branches:

- Codex writes to `codex/*`.
- Claude Code writes to `claude/*`.
- `main` is stable and merged through PRs.
- `proposal/*` branches are read-only for agents unless Jonathan explicitly approves direct pushes.
- Agents may build from any remote branch by creating a child branch.

## Consequences

This makes collaboration a little more formal, but it keeps history understandable. It also allows Jonathan to compare Codex and Claude work before deciding what merges into `main`.

## Owner

Jonathan owns final merge decisions. Each agent owns the branch it creates.
