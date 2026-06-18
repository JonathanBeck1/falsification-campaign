# Decision: Similar Event Retrieval V0

Date: 2026-05-20

## Decision

Add deterministic point-in-time similar-event retrieval over stored
`news_events`.

## Boundary

- Retrieval is research-only.
- Retrieval does not create orders, positions, portfolio weights, or broker
  calls.
- Retrieval uses stored event text and deterministic scoring only.
- Retrieval results are rankings for review/calibration, not absolute signal
  probabilities.
- Default weighting gives text relevance twice the weight of recency or
  importance so a recent but unrelated event does not outrank an older event
  that actually matches the query language.

## Inputs

- Stored `Event` rows.
- Required `as_of` cutoff.
- Optional source and event-type filters.

## Outputs

- Markdown reports from `similar-events`.
- Candidate context reports from `candidate-context`, which attach similar
  historical events to scored research candidates.
- `event_retrievals` audit rows showing when an event appeared in a retrieval
  result.

## Point-In-Time Rule

The retrieval candidate set excludes events whose `observed_at` or
`classified_at` is at or after the `as_of` cutoff. Retrieval-log recency also
ignores rows with `retrieved_at` at or after that cutoff.

## Rationale

This creates the first calibration primitive: when a new enriched event appears,
the system can ask which past events are similar before any backtest or alert
logic treats the event as interesting.
