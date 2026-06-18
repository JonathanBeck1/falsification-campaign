# Codex delegation (save Opus usage)

The idea: **Opus plans + reviews; Codex (GPT) does the mechanical grunt work.**
Opus stays the authority on anything subtle (the backtest engine, risk math,
research conclusions). Codex handles well-scoped, low-judgement edits so we burn
fewer Opus tokens.

Codex CLI is installed (`codex`, auth in `~/.codex/auth.json`). It runs
non-interactively via `codex exec`.

## When to delegate to Codex

Good (mechanical, easy to verify from a diff):
- Boilerplate: new CLI flags, dataclass fields, plumbing an argument through.
- Repetitive edits across many files (rename, signature change).
- Writing unit tests for a function whose contract Opus already specified.
- Docstrings, type hints, small refactors with no behavior change.
- Regenerating a report/table from an existing script.

Keep on Opus (judgement, correctness-critical):
- The options backtest engine / P&L marking / risk bounds.
- Research methodology and what a result *means*.
- Anything touching secrets, money, or the `.env` creds patch.
- Deciding whether a change is correct (review the Codex diff yourself).

## How

```bash
# One-liner spec:
scripts/codex_task.sh "Add a --max-hold-minutes int flag (default 390) to the \
options-backtest-intraday-iron-condor subparser in src/trader/cli.py and thread \
it into IntradayIronCondorBacktestConfig. Do not change engine logic."

# Longer spec from stdin:
scripts/codex_task.sh - <<'SPEC'
<multi-paragraph spec>
SPEC
```

Codex runs sandboxed (`workspace-write`): it edits files but never touches git
history. It prints what it changed; **Opus then reviews `git --no-pager diff`**
before anything is committed.

## Review checklist (Opus does this every time)
1. `git --no-pager diff` — read every hunk. Codex is not trusted blindly.
2. Run the relevant check (`.venv/bin/python -c 'import ...'`, a unit test, or a
   short backtest) to confirm no behavior regressed.
3. Only then stage/commit on a `claude/*` branch.

## Structured output (optional)
For machine-readable results, pass `--output-schema schema.json` to `codex exec`
and read its final JSON — useful when delegating "find all call sites of X".
