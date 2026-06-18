# Decision: Event Candidate Scoring V1

Date: 2026-05-20

## Decision

Add deterministic event candidate scoring over enriched `news_events`.

## Boundary

- Candidate scoring is research-only.
- Candidate scores are not trading orders.
- Candidate scores do not size positions.
- Candidate scores do not access account state, fills, positions, or broker APIs.
- Candidate reports are review artifacts for humans and later backtesting.

## Inputs

- Stored `Event` rows.
- Latest valid `event-enricher-v1` / `tmpl-v1` model output.

## Outputs

- Markdown reports under `output/reports/`.
- Dashboard candidate rows.

## Rationale

This creates a bridge from LLM enrichment to empirical research while preserving
the rule that trading decisions must remain deterministic, backtested, and risk
gated.
