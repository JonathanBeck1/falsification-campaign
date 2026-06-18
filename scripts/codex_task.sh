#!/usr/bin/env bash
# Delegate a mechanical / well-specified task to Codex to save Opus usage.
#
# Codex (GPT) does the grunt work in a sandboxed workspace-write session; Claude
# (Opus) writes the precise spec and REVIEWS the resulting diff before anything is
# committed. Codex never touches git history here -- it only edits files.
#
# Usage:
#   scripts/codex_task.sh "Add a --foo flag to cmd_bar in src/trader/cli.py, default 1.0"
#   scripts/codex_task.sh -            # read the (longer) spec from stdin
#
# After it runs, review with:  git --no-pager diff
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 \"<task spec>\"   (or '-' to read spec from stdin)" >&2
  exit 2
fi

# Standing guardrail prepended to every spec. The workspace-write sandbox blocks
# writes to .git, so any git command Codex tries (branch/switch/commit) hard-fails
# and wastes the run. Claude owns all git; Codex only edits files + runs tests.
GUARD="IMPORTANT GROUND RULES:
- Do NOT run any git commands (no git switch/checkout/branch/add/commit/stash/restore). The sandbox blocks writes to .git and they WILL fail. Claude handles all branching and commits.
- Only create or edit files, and run tests / python directly to verify.
- Do not edit files outside the stated scope. Report the final test summary line when done."

if [[ "${1:-}" == "-" ]]; then
  SPEC="$(cat)"
else
  SPEC="$*"
fi
PROMPT="${GUARD}

=== TASK ===
${SPEC}"

echo "=== Delegating to Codex (workspace-write, sandboxed, non-interactive) ===" >&2
# Fully automated: never pause for approval. Codex can read/write inside the repo
# sandbox but cannot escalate or touch anything outside it; Claude reviews the diff.
codex exec \
  --sandbox workspace-write \
  -c approval_policy="never" \
  -C "$REPO" \
  --skip-git-repo-check \
  "$PROMPT"

echo >&2
echo "=== Codex finished. Files it changed: ===" >&2
git -C "$REPO" --no-pager diff --stat >&2
echo "Review the full diff before committing:  git --no-pager diff" >&2
