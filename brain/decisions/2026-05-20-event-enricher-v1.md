# Decision: Event Enricher V1 Scope

Date: 2026-05-20

## Decision

Build Event Enricher V1 as an asynchronous analyst-only worker over stored
`news_events`.

## Boundaries

- The LLM receives one event at a time.
- The LLM never sees account state, orders, fills, portfolio weights, or prices.
- The LLM output is validated before persistence.
- The output is stored in `model_outputs_json` with classifier
  `event-enricher-v1` and prompt version `tmpl-v1`.
- Deterministic normalizers own `classified_at`.
- The enricher queue is based on missing `model_outputs_json` entries, not
  `classified_at IS NULL`.

## Initial Safety Rules

- Unit tests mock the LLM; live API calls are manual only.
- `enrich-events --mock-llm` uses a deterministic local analyst stub for
  no-key pipeline testing only.
- `seed-events --demo` exists only to populate local deterministic examples; it
  is not a market data adapter.
- `review-events --only` supports manual review slices for enriched, rejected,
  and missing events.
- Default daily budget is `TRADER_LLM_DAILY_BUDGET_USD=1.0`.
- Candidate scoring and trade execution remain separate future work.
