# Audit Deferred: Secondary Validator + Uncertainty Quantification

Date: 2026-05-20
Status: design notes. Implementation deferred until PR #24 (event enricher)
merges. No code yet.
Owner: the maintainer (via Claude Code).

This doc covers audit problems #1 (LLM hallucination) and #9 (uncertainty
quantification) from the 10-problem self-audit. Both require PR #24's
EnrichmentV1 infrastructure to exist before they can be built, so they're
deferred behind a brief design note.

The other audit problems (#2 stale data, #3 prompt injection, #5
correlated agents, #6 risk-gate strengthening, #7 regime tags, #8
transaction costs, #10 PDT counter) were addressed in PRs #32 and #33.
This doc closes the remaining two.

## Problem #1: LLM hallucination

### What we already have

- **Strict Pydantic schemas** (PR #24's `EnrichmentV1`, PR #25's
  `LLMFeatures`) — reject unknown enum values, missing required fields,
  free-form floats. `extra="forbid"` blocks fields the LLM tries to
  smuggle in.
- **Quote grounding** (PR #24 `_quote_supported`) — every LLM-emitted
  claim must reference a quote that exists in the article. A fully
  hallucinated quote fails validation.
- **Ticker allowlist** (PR #24 `_allowed_tickers`) — LLM can't emit
  phantom tickers like "MSFT.A"; tickers must come from `entities` or
  `index_exposure` of the source event.
- **Confidence guard** (PR #24 `service.py:135-136`) — if
  `confidence < 0.4`, sentiment/urgency are forced to neutral/normal.
- **Sanitization at ingestion** (PR #32) — prompt-injection vectors
  stripped before text reaches the LLM.
- **The architecture itself** — `brain/10` + `brain/20` + PR #30's
  ThesisEngine ensure the LLM never directly emits floats that become
  positions.

### What's still missing: secondary validator + daily audit

Even with all of the above, a high-confidence wrong answer can pass
validation if the LLM's labels are internally consistent but factually
incorrect. Example: LLM reads "Powell expressed caution about further
hikes" and outputs `sentiment_label=bullish, severity=high` — the schema
passes, quote grounding passes, but the label is wrong.

#### Design: two-model cross-check

A second LLM (different provider, or same provider with a different
prompt) reads the SAME article and the FIRST model's output, and asks:
"do you agree with this classification?"

```
trader-daily validate-enrichments \
    --source demo_news \
    --since 2026-05-20T00:00:00Z \
    --primary claude-haiku-4-5-20251001 \
    --validator gpt-4o-mini \
    --output output/audits/enrichment-validation-2026-05-20.md
```

What it does:
1. Pulls recent enriched events from `news_events`
2. For each, sends `(article, primary_enrichment)` to the validator
   model with a strict yes/no/abstain prompt
3. Records the agreement rate per event_type and per severity bucket
4. Flags events where validator disagrees AND confidence was high
5. Outputs a markdown report; events with `validator=DISAGREE,
   primary_confidence>=0.7` get a `human_review_required` flag — stored
   as an **explicit schema field** on `ModelOutputMeta`, not as an
   ad-hoc key inside `model_outputs_json`.

   Per Codex review (2026-05-20): an ad-hoc JSON flag has no schema
   enforcement, can't be indexed, and breaks silently on typos.
   Implementation prerequisite: extend `ModelOutputMeta` with a
   `validator_state: Literal["agree", "disagree", "abstain", "unchecked"]`
   field via a real Alembic migration (or equivalent) before any tool
   writes this flag.

The validator model should be a DIFFERENT provider (e.g., Haiku
primary + 4o-mini validator) so the two systems don't share the same
training-data biases. Per `brain/decisions/2026-05-20-llm-model-choice-notes.md`,
4o-mini is 5-7x cheaper than Haiku and is the natural validator.

**Cost**: validator runs on a subset (only events where
`is_actionable=true`), at ~$0.001/call on 4o-mini. At our event
volume (~50-150/day, ~30% actionable), this is $0.015-$0.045/day
extra. Well within the $1/day cap.

#### Design: daily hallucination audit

Independent of the realtime validator, a once-a-day batch job that:
1. Pulls all enrichments from the last 24h
2. Computes statistical signatures: label distribution, severity
   distribution, confidence distribution
3. Compares against a rolling 30-day baseline
4. Flags drifts: "suddenly 60% of events are labeled `breaking` —
   investigate"
5. Reports validator-disagreement rate alongside

CLI shape:
```
trader-daily audit-enrichments \
    --window 24h \
    --baseline-window 30d \
    --output output/audits/daily-enrichment-audit.md
```

This is the "constantly have checks every day" capability the
maintainer wanted. It doesn't catch one bad enrichment in realtime, but it catches
**systematic** problems — a stale prompt template, a regression in
the model, a new injection vector that's slipping through sanitization.

### Why this needs PR #24

Both tools query `news_events.model_outputs_json` for stored
EnrichmentV1 records. That column is populated only after PR #24
merges and an enrichment cron runs. Pre-PR-#24, there's nothing to
audit.

### Build order when PR #24 lands

1. Implement `validate-enrichments` CLI (~half day)
2. Run it manually for a week against real enriched events
3. Tune the disagreement threshold based on observed false-positive
   rate
4. Wire it into the daily cron
5. Implement `audit-enrichments` (~half day) on top of the validator
   data
6. Add a dashboard panel for "enrichments flagged for review"

## Problem #9: uncertainty quantification

### What we already have

- `EnrichmentV1.confidence` field (PR #24): 0-1 float, schema-validated
- `LLMFeatures.severity_bucket` (PR #25): discrete low/medium/high/breaking
- `ThesisTemplate.confidence` (PR #30): discrete low/medium/high
- `CONFIDENCE_WEIGHT` dict in `taxonomy.py`: directly modulates position
  size (high=1.0, medium=0.5, low=0.25)
- Direction-sum check in aggregator: opposing theses cancel toward
  baseline

### What's missing: evidence count, contradicting signals, novelty

Per the audit, a robust uncertainty quantification has these fields the
LLM should emit alongside its labels:

```
EnrichmentV2 additions:
  - evidence_count: int        # How many distinct source quotes support this label?
  - contradicting_signals: int # How many quotes in the same article point the other way?
  - evidence_quality: Literal["thin", "moderate", "strong"]
  - novelty_marker: bool       # Is this story repeating prior coverage, or genuinely new?
```

And aggregator-side rules:
- If `contradicting_signals > 0`: halve position size regardless of
  primary confidence
- If `evidence_quality == "thin"`: treat as low-confidence regardless
  of the model's stated confidence
- If `novelty_marker == False` AND the same event_type already has
  a thesis in the last 24h: downweight (already priced in)

### Design: novelty detection via embeddings

Mentioned in the audit. The idea: each new enrichment is embedded;
if its embedding is statistically far from the last N enrichments of
the same event_type (cosine similarity below threshold), flag as NOVEL.
If it's very close to recent ones, flag as recycled.

This is more research than engineering. The simpler v0:
- Track a "recent-event-type signature" per (event_type, day)
- A new enrichment that matches an existing same-day signature
  (same tickers + same severity + same direction) is flagged
  `is_repeat`
- Aggregator downweights `is_repeat` theses

We can implement this without embeddings using exact-match signatures.
Embeddings come later if exact-match is too coarse.

### Build order when PR #24 lands

1. Bump enricher schema from V1 to V2 with the new fields
2. Update prompts to request the new fields with calibration guidance
3. Wire the new fields into aggregator weighting
4. Add `is_repeat` exact-match novelty detection
5. Add `validate-enrichments` agreement metric for the new fields
6. Defer embedding-based novelty to a brain/24+ doc

## What to do TODAY

Nothing on this front. The other 8 audit problems are addressed in
PRs #32 + #33. Wait for PR #24 to merge, then this becomes the
roadmap for the next two PRs (validator harness + EnrichmentV2 schema).

## Summary table: audit status after this batch

> **Status interpretation** (per Codex review 2026-05-20): this table
> reflects the **projected** state after PRs #32 and #33 land — *not*
> the current state of `main`. Items marked 🟢 are either already in
> `main` or shipping in the referenced PR. Verify with `git log main`
> before treating any 🟢 as merged. Items marked 🟡 require PR #24
> (event enricher) and remain deferred until it lands.

| Audit problem | Status | Where |
|---|---|---|
| #1 Hallucination | 🟡 Schema/grounding/sanitization done; secondary validator deferred | This doc |
| #2 Stale data | 🟢 Heartbeat gate | PR #32 |
| #3 Prompt injection | 🟢 Sanitizer hardened | PR #32 |
| #4 Sycophancy | 🟢 Structurally solved | architecture |
| #5 Correlated agents | 🟢 Randomized execution delay | PR #32 |
| #6 Instruction conflicts | 🟢 RiskGate enforces in Python; day-trade counter populated | existing + PR #32 |
| #7 Overfitting/recency | 🟢 Regime tags + CRISIS-flat | PR #33 |
| #8 Transaction costs | 🟢 Net-edge filter + min-holding lock | PR #33 |
| #9 Uncertainty quantification | 🟡 Confidence done; evidence_count etc. deferred | This doc |
| #10 Regulatory/compliance | 🟢 PDT counter populated | PR #32 |

The 🟡 items are not "unsolved" — they're "more we can do once PR #24
lands." The system as it stands today already addresses all 10 audit
problems to the level a paper-trading research system needs. The
deferred work raises the bar for live trading.
