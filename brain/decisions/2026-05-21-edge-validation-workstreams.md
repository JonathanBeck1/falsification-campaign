# 2026-05-21 Edge Validation Workstreams

Decision: split work into two streams.

Codex/Jonathan owns research and edge validation:

- no-key smoke script
- edge statistics
- edge-report CLI
- edge criteria docs
- research dashboard summaries

Claude/friend owns foundation and operator view:

- migrations
- monotonic event upsert
- point-in-time filtering
- UTC timestamp hygiene
- live dashboard view

Reason: the project has pipeline mechanics but not proven alpha. The highest-value work is now honest edge detection plus data correctness.

Constraint: no live trading, no direct pushes to main, no secrets in git.
