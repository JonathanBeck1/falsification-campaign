# Terminal Interactivity V1

Date: 2026-05-21
Status: accepted

## Decision

Make the Streamlit terminal an operating surface for research review:

- news tape rows carry durable `event_id` values
- NEWS DESK supports ticker/source/type/urgency filters
- tape rows link to `?terminal_module=NEWS+DESK&event_id=...`
- the article inspector follows the selected event when present
- RESEARCH previews selected Markdown reports from `output/reports/`
- BACKTEST exposes a selected research run inspector and artifact paths

## Why

The dashboard looked polished, but the operator could not yet select the exact
evidence they were reviewing. This pass keeps the terminal research-only while
turning it from a static display into a navigable review console.

## Boundaries

- No trading controls.
- No Alpaca order actions.
- No auth or multi-user behavior.
- Report preview is limited to files under `output/reports/`.
- Query params select evidence only; they do not mutate the database.

## Operator Workflow

Use NEWS DESK as the first triage surface:

1. Filter by ticker, source, event type, or urgency.
2. Click a tape row to persist the selected event in the URL.
3. Review the article inspector before moving to EVENT LAB.
4. Use RESEARCH to preview generated Markdown reports.
5. Use BACKTEST to inspect the research run that produced those reports.

## Next

The next pass should move from review visibility toward alert routing and
paper-trade-intent staging, while preserving the explicit research-only
boundary until backtests justify a signal.
