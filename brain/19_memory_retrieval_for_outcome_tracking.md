# Memory Retrieval for Outcome Tracking

Date: 2026-05-19
Status: draft proposal. Doc-only. No code yet.
Owner: a collaborator (via Claude Code).

Adapted from Park et al., *"Generative Agents: Interactive Simulacra of
Human Behavior"* (Stanford / Google, 2023; Apache-2.0). We borrow the
retrieval-scoring formula only — we do not copy code. License-clean.

## Why this exists

The next concrete work after the spider + enricher land is **outcome
tracking on enriched events**: for each `news_events` row, measure forward
returns (5m, 1h, 4h, 1d, etc.) and link them back to the event's enriched
features. That feeds the deterministic candidate scorer in Milestone 3 and
the honest backtest in Milestone 4.

But "outcome tracking" by itself is just a join. The real product question
is one step up: *"when a new event arrives, which past events are most
relevant for predicting what happens next?"*

That's a retrieval problem. Park et al.'s memory-stream paper has the
cleanest published prior art: a closed-form scoring function over three
components that fits our event-store schema almost exactly.

This doc ports that formula to our event store and specifies the schema
additions, the retrieval function, and the consumers.

## The Park et al. retrieval formula (paraphrased)

For a query `q` and a memory record `m`, score:

```text
retrieval_score(m, q) = α_recency · recency(m)
                      + α_importance · importance(m)
                      + α_relevance · relevance(m, q)
```

Each component normalized to `[0, 1]` (the paper uses min-max across the
candidate set before weighting).

- **recency** = `exp(-decay_rate · hours_since_last_retrieval(m))`. The paper
  decays from *last retrieval*, not *creation* — a memory retrieved often
  stays "fresh." We adapt this for trading (see below).
- **importance** = an integer score `0..10` assigned by an LLM at memory
  creation time, in answer to *"How poignant is this memory?"*
- **relevance** = cosine similarity between the query embedding and the
  memory embedding.

The paper's default weights are `α_recency = α_importance = α_relevance = 1`.

## Mapping to our event store

Our `news_events` table already covers most of what we need:

| Park concept | Our field(s) | Status |
|---|---|---|
| memory record | `news_events` row | ✓ exists |
| memory creation time | `ingested_at` | ✓ exists |
| memory recency proxy | `published_at` (event time) — see "Recency" below | ✓ exists |
| importance score | composed from `urgency`, source credibility, `event_type` prior, narrative intensity | ✓ all fields exist |
| memory relevance | text similarity to a query — BM25 over `title + summary` for v0 | **needs index** |
| memory embedding (v2) | future column once BM25 ceiling is hit | deferred |

Two **new sidecar tables**, no mutations to existing `news_events` columns:

1. **`event_retrievals(event_id, retrieved_at, query_hash)`** — log of every
   time an event entered a retrieval set. `news_events` itself is
   **immutable** after enrichment, which matters for backtest
   reproducibility (see "Point-in-time discipline" below). Park's
   "retrieval freshens memory" recency is computed by joining this log,
   not by mutating the row.
2. **`event_embeddings(event_id, model, dim, vector BLOB, created_at)`** —
   only created when we move from BM25 to embeddings in a follow-up PR.
   Keyed by `(event_id, model)` so multiple model versions can coexist
   during migration.

Why sidecar tables rather than columns on `news_events`:

- Keeps `news_events` rows **frozen** after enrichment — critical for
  point-in-time backtests. Any mutation to a row is a lookahead-bias
  risk.
- Lets us drop / rebuild retrieval state without touching the canonical
  event store.
- SQLite `ALTER TABLE ADD COLUMN` is safe under WAL but still touches
  every row; sidecars avoid that on a populated `news_events`.

## Importance, our version

Park et al. spend an LLM call per memory just to assign an importance
score for *narrative significance*. We don't need to — the enricher
(`brain/18`) already computes the right ingredients, and importance can be
a deterministic composition.

**Honest semantic note**: the paper's importance reflects *narrative
poignancy*; ours reflects *operational salience for trading*. The shape
(scalar in `[0,1]` per memory, used as a weighted component) is the same;
the semantics are different. This is a real divergence, not a one-to-one
port. Listed in §Attribution.

Proposed v0 composition:

```text
importance(m) = clamp_0_1(
    0.35 · urgency_weight(m.urgency)        # breaking=1.0, high=0.7, normal=0.4, low=0.2
  + 0.20 · m.source_credibility              # already in [0,1]
  + 0.15 · m.novelty_score                   # already in [0,1]
  + 0.15 · narrative_intensity(m)            # = abs(sentiment_score) * urgency_weight; "how loud is this?"
  + 0.15 · event_type_prior(m.event_type)    # see table below
)
```

`narrative_intensity` replaces the earlier `enricher_confidence` field —
classifier confidence measures "how sure are we this is X," not "how much
does X matter." Magnitude of sentiment is a better proxy for the latter.

`event_type_prior` injects the obvious truth that
`fed_commentary / guidance_raise / guidance_lower / mna` are intrinsically
more important than `other`:

| event_type | prior |
|---|---|
| `fed_commentary` | 1.0 |
| `guidance_raise`, `guidance_lower` | 1.0 |
| `earnings_surprise` | 0.9 |
| `mna`, `regulatory_action` | 0.9 |
| `macro_surprise` | 0.85 |
| `analyst_upgrade`, `analyst_downgrade` | 0.6 |
| `unusual_social_velocity` | 0.5 |
| `other` | 0.3 |

All five weights and the priors are **config, not constants** (see
`config.RetrievalWeights`). Ablate one at a time once we have outcome
labels — see "Tests" below.

Cheaper than Park (zero extra LLM calls), more auditable (every component
is already graded by the human review pass on the enricher).

## Recency, our version

Park's `exp(-λ · hours_since_last_retrieval)` works as-is, but we need to
think about what "hours" means for trading events. Two cases:

1. **"Find similar past events for this new event's calibration lookup"** —
   probably want a *long-half-life* decay (e.g. `λ` such that 6 months ≈
   half score). A relevant fed_commentary from 2025 still matters.
2. **"Find recent events that might still be in the tape"** — short
   half-life, e.g. hours.

Surface `decay_half_life_hours` as a function argument; default to ~120
days for calibration retrieval and a separate ~6h for real-time use. Do
not hard-code one decay for both.

**Recency reference point**: `hours_since_last_retrieval` is computed from
the `event_retrievals` log (not by mutating `news_events`). For an event
that has never been retrieved, fall back to `hours_since_published`.
Append a new `event_retrievals` row whenever a memory enters a retrieval
set (top-K, not just top-1). Same Park semantic; immutable canonical
store.

## Relevance, our version

**V0 is BM25 over `title + " " + summary`.** Not embeddings.

Why BM25 first:

- **Zero new heavyweight deps.** `rank_bm25` is ~50KB pure Python, MIT.
  Compare to ~150MB for `sentence-transformers` + `all-MiniLM-L6-v2`.
- **Deterministic, debuggable.** A retrieved hit can be explained by the
  exact term overlaps. Embedding cosine similarity is a black box.
- **Fits `brain/15`'s "deterministic filters first" rule.** Local
  transformer inference isn't an LLM call, but pulling in 150MB of model
  weights silently as a v0 dep is the kind of architecture decision that
  deserves a separate proposal.
- **Establishes a quality baseline.** When we later add embeddings, we'll
  know whether they actually help (versus just feeling more sophisticated).

BM25 implementation:

- Pre-tokenize `title + " " + summary` per event; persist tokens in a
  `event_tokens(event_id, tokens_json)` sidecar OR compute on the fly
  (small corpus, sub-100ms either way at <100k events).
- Build a `BM25Okapi` index over the filtered candidate set per retrieval
  call. Yes, this is `O(N)` index build per call; for <100k events it's
  still sub-100ms. Caching the index in a module-level lru is a follow-up.
- Tokenizer: lowercase, split on word boundaries, drop stopwords. NLTK
  English stopwords is fine; punkt is optional.

**Future v2 (separate PR)**: embeddings via `sentence-transformers`
`all-MiniLM-L6-v2` (384-dim, MIT), stored in `event_embeddings` sidecar.
Triggered when BM25 retrieval quality clearly caps out in manual review.
Same `RetrievalHit` interface, swap the `relevance(m, q)` implementation.

## The retrieval function

Public API:

```python
def retrieve_relevant_events(
    *,
    store: Store,
    query: Event | str,                  # an unenriched new event, or raw text
    as_of: datetime,                     # POINT-IN-TIME CUTOFF — see below; required, no default
    k: int = 20,
    min_candidates: int = 30,            # cold-start guard: if the filtered set < this, return []
    decay_half_life_hours: float = 24 * 120,
    weights: RetrievalWeights = DEFAULTS,  # {recency, importance, relevance}
    filters: RetrievalFilters | None = None,  # event_type, source, asset_scope
    log_retrieval: bool = True,          # if True, append rows to event_retrievals
) -> list[RetrievalHit]:
    ...
```

### Point-in-time discipline (the bit that prevents backtest lookahead)

`as_of` is **required, no default**. The implementation must:

1. Filter the candidate set to `m.observed_at < as_of` AND
   `m.classified_at < as_of` (an event we hadn't yet enriched at the
   decision time doesn't have enrichment features to retrieve on).
2. Filter the `event_retrievals` log to entries with `retrieved_at < as_of`
   when computing recency. A future retrieval of `m` cannot freshen its
   past recency.
3. Reject calls where `as_of > now()` (sanity check; live use passes
   `now()`).

Without this, a backtest at time T would silently retrieve enriched memories
created or refreshed *after* T, and the entire calibration loop is dead.
Tests below cover this.

### Score normalization

For each retrieval call:

1. Compute raw `recency_i`, `importance_i`, `relevance_i` for every candidate.
2. Min-max normalize **each component independently across the filtered
   candidate set** so the three components are in `[0, 1]`.
3. Weighted sum: `score_i = w_r · rec_i + w_i · imp_i + w_rel · rel_i`.
4. Sort descending; take top-`k`.

Per-query normalization, not global. Park et al. do this implicitly; we
make it explicit so reviewers know the scores aren't comparable across
retrieval calls (they're rankings, not absolute relevance).

### Cold start

If `len(candidates) < min_candidates` after filters, return `[]` rather
than a noisy top-K. With <30 events under a filter, retrieval is meaningless.
The consumer (outcome-tracking calibration) handles empty results by
flagging the event as "no calibration baseline available."

### `RetrievalHit` shape

```python
@dataclass(frozen=True)
class RetrievalHit:
    event: Event
    final_score: float
    sub_scores: dict[str, float]   # {"recency": ..., "importance": ..., "relevance": ...}
    sub_scores_raw: dict[str, float]  # pre-normalization, for debugging
    rank: int
```

Exposing sub-scores prevents a "why did it retrieve this?" black-box
problem. Cheap to compute, useful for manual review.

**Performance**: with sub-100k events, BM25 index build + score is
sub-100ms on a laptop. Only worth introducing FAISS / hnswlib if we ever
move to embeddings AND the table crosses ~500k rows. YAGNI for v0.

## Who consumes this

Three concrete consumers, in priority order:

1. **Outcome-tracking calibration** (the lane that motivated this doc).
   For each *enriched* event, retrieve the top-K most-similar past
   *enriched-and-outcome-measured* events. Compute the empirical
   distribution of their forward returns. Surface that as `calibration_v1`
   features on the row: *"events like this one historically moved SPY by
   median X% at 1h with N=K observations."* That's the candidate scorer's
   input.

2. **Manual review pipeline** (`brain/18` Milestone 1 follow-up). When a
   human grades a new enriched event, surface the top-3 similar past
   events with their gradings — gives the grader context and exposes
   systematic mislabeling faster.

3. **Daily snapshot context for HybridBrain**. The existing brain already
   sees recent news; retrieval lets it also see the *most-similar past
   events* across history. Strictly an analyst feature (no decision-making
   change). Optional v0 consumer.

## What this is NOT

- Not RAG over filings (out of scope for v0; that's a separate proposal).
- Not the candidate scorer itself — this is the *retrieval* primitive the
  scorer uses.
- Not "the LLM decides which past events matter." Retrieval is
  deterministic Python (BM25) + arithmetic. The LLM only ever sees the
  *result* of retrieval, never decides retrieval itself.
- Not a copy of Park et al.'s codebase. We port the *formula*, which is the
  paper's contribution. Their code is Django+Phaser game-world plumbing —
  irrelevant to a SQLite event store.
- Not the "reflection" layer from the paper (synthesizing higher-level
  insights from clusters of retrieved memories). Punted for v0; revisit
  after outcome-tracking labels exist and we can measure whether
  reflections add signal vs. just bloating context.

## Tests

`tests/financial/test_retrieval.py`:

1. **Determinism**: two calls with the same `as_of`, filters, and
   weights over the same store produce identical `RetrievalHit` lists
   (modulo `event_retrievals` writes).
2. **Recency monotonicity**: among two otherwise-identical candidates,
   the one published closer to `as_of` scores higher on the recency
   component.
3. **Point-in-time correctness**: an event with `observed_at` after
   `as_of` is NEVER in the returned set, even if it has the highest
   relevance.
4. **Retrieval-log point-in-time**: a memory retrieved at T+1 does not
   affect a retrieval at T (i.e. `event_retrievals` rows with
   `retrieved_at >= as_of` are filtered).
5. **Cold-start**: with `len(candidates) < min_candidates`, returns `[]`.
6. **Normalization**: when one component (e.g. importance) is constant
   across the candidate set, that component contributes zero variance to
   the final score (degenerate min-max → all zeros).
7. **Importance composition**: changing the weight on `event_type_prior`
   measurably reranks candidates that differ only in `event_type`.
8. **Filters**: `filters.event_type=["fed_commentary"]` excludes everything
   else.

No LLM calls in these tests — retrieval is fully deterministic.

## Sequencing

1. (Now) This doc reviewed. No code yet.
2. (After PRs #11 #12 #13 land) Re-run `fetch-events` for real volume.
3. (Then) Schema migration: create `event_retrievals` sidecar. **Does not
   block on the enricher** — BM25 retrieval works on raw `title +
   summary`, no enrichment needed. We just won't have `importance` until
   the enricher lands. Could ship retrieval with importance disabled
   (weights `{0, 0, 1}`) for an even earlier baseline.
4. (Then) Land the enricher (per `brain/18`). Once enrichment exists,
   activate the importance component of the formula.
5. (Then) `retrieve_relevant_events()` function + tests + CLI smoke
   command `trader-daily similar-events --event-id evt_... -k 10
   --as-of 2026-05-19T13:00:00Z` for manual inspection.
6. (Then) Wire into outcome-tracking calibration first, then manual review,
   then HybridBrain context.
7. (Later) Embeddings v2 PR (separate proposal): `event_embeddings`
   sidecar + `sentence-transformers` integration if BM25 quality caps out.

## Open questions for the maintainer

1. **BM25-first v0 path**: agree with starting on BM25 instead of pulling
   in ~150MB of `sentence-transformers`? The relevance interface stays
   the same; swap is a follow-up PR.
2. **Decay half-life defaults**: 120 days for calibration retrieval feels
   right for SPY/QQQ macro-flavored events but might be wrong for
   earnings. Per-event-type defaults? Or just leave it as a kwarg and tune
   later?
3. **Importance weights**: the five-component composition above is my best
   guess. Worth a manual review batch to tune? Or leave at the proposed
   weights until we have outcome data?
4. **`event_type_prior` table**: are the priors I assigned reasonable?
   These are subjective until we have outcome data.
5. **Embedding-v2 trigger**: what counts as "BM25 quality caps out"?
   Proposal: when manual review of retrieval sets agrees with the top-K
   less than ~60% of the time on the relevance dimension. Open to a
   different threshold.

## Attribution

Generative Agents repo: https://github.com/joonspk-research/generative_agents
(Apache-2.0). Paper: Park, O'Brien, Cai, Morris, Liang, Bernstein (2023),
*Generative Agents: Interactive Simulacra of Human Behavior*, UIST 2023.

Memory-stream / retrieval formula described in §A.2 of the paper. Our
adaptation diverges in three ways:

1. Importance is deterministic composition of enricher features, not an
   extra LLM call.
2. Recency decay is parameterized for trading horizons, not the paper's
   single decay constant.
3. Embeddings are local + small, not OpenAI Ada-002 as the paper used.

The formula structure (sum of three normalized components, weighted) is
the borrowed idea. Formulas are not copyrightable; this is fair use of an
academic paper's contribution. No NOTICE file required since we copy zero
lines of their code.

## Review history

Reviewed once by an independent agent (verdict: `minor-fixes`, 6 items).
All six applied before push:

1. Added required `as_of` parameter + point-in-time filter on both
   `news_events` and `event_retrievals`. The biggest catch — without
   this, backtests would silently leak future similarity.
2. Moved `last_retrieved_at` out of `news_events` into a sidecar
   `event_retrievals` log table. Keeps the canonical event store
   immutable.
3. Replaced "embedding column + model column on `news_events`" with a
   sidecar `event_embeddings` table keyed by `(event_id, model)`.
4. Reworked importance composition: replaced `enricher_confidence` (which
   measured "how sure" rather than "how important") with
   `narrative_intensity` and added an `event_type_prior` table.
5. Shipped BM25 over `title + summary` as the v0 relevance baseline
   instead of `sentence-transformers`. Removes the 150MB dep, fits the
   "deterministic filters first" tier rule, establishes a baseline before
   the embeddings PR.
6. Made the per-query min-max normalization step explicit in the API
   contract, not an unstated detail.

Also added: explicit `min_candidates` cold-start guard, tests section,
attribution note about the importance-semantics divergence (operational
salience ≠ narrative poignancy).
