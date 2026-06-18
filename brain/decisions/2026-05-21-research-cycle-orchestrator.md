# Research Cycle Orchestrator V1

Date: 2026-05-21
Status: accepted

## Decision

Add a repeatable research-cycle command that runs the evidence loop and records
each run in SQLite:

`fetch-events -> enrich-events -> score-events -> candidate-context -> outcome-backtest -> outcome-review -> manifest`

The new `research_runs` and `research_run_artifacts` tables are the audit
ledger for these runs. Generated Markdown reports remain in `output/reports/`,
while the database keeps the run status, counts, paths, and errors visible to
the terminal.

## Why

The terminal needed durable evidence history before we add alerts or paper
trade intents. A polished dashboard is only useful if it can answer which
research runs happened, what they produced, and whether they failed.

## Boundaries

- Research-only.
- No live Alpaca trading.
- No options execution.
- No edge claims.
- `--mock-llm` supports no-key local testing.
- Yahoo remains the free fallback data source for outcome bars.

## Operator Workflow

```bash
trader-daily research-cycle \
  --mock-llm \
  --benchmark SPY \
  --entry-time observed_at \
  --group-by event_type \
  --group-by thesis_bucket \
  --reports-dir output/reports
```

Use `--skip-fetch` when testing against already stored events.

## Next

The next PR should make the terminal more interactive around the data created
here: selected news rows, report previews, and richer run inspectors.
