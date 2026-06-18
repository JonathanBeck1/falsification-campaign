# Research Cycle To Paper Trading Roadmap

Date: 2026-05-21

The next product push should turn the terminal from a strong operator surface into a repeatable evidence machine. The detailed implementation plan lives at:

`docs/superpowers/plans/2026-05-21-research-cycle-to-paper-trading.md`

## Build Order

1. **Research Cycle Orchestrator**
   One command runs fetch, enrich, score, outcome backtest, outcome review, and manifest generation. This creates durable `research_runs` history for the terminal.

2. **Terminal Interactivity**
   Add filters, selected news rows, report previews, and run inspectors. This makes the terminal operational instead of just visual.

3. **Data Quality And Backfill**
   Persist source fetch status, flag stale news, support source-specific backfills, and surface source quality in the terminal.

4. **Phone Alerts**
   Add ntfy and multi-notifier routing for run results, source failures, high-conviction candidates, and risk issues.

5. **Paper Trading Readiness**
   Create auditable trade intents from candidates, risk-review them, optionally simulate them through `SimBroker`, and show them in a `PAPER DESK` terminal module.

## Boundaries

- No live Alpaca trading in this roadmap.
- No options execution.
- No edge claims until the research-cycle output has enough sample size and out-of-sample history.
- No SaaS work yet.

## Why This Order

The system needs evidence before more automation. A terminal that looks good is useful, but a terminal that shows repeatable research runs, source health, and risk-reviewed paper intents is the real foundation for deciding whether this strategy has edge.
