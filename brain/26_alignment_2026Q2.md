> ⚠️ **UNSIGNED DRAFT — DO NOT REFERENCE.**
> This file is a skeleton with placeholders (`<<< FILL IN >>>`) that the maintainer
> and the collaborator must resolve and counter-sign before it becomes load-bearing. **No
> other code, doc, or PR may cite this file as authority until both author
> commit lines in Section 6 are filled by separate commits.** Treat it as
> non-existent until then.

---

# 26 — 2026 Q2 Alignment

| Field | Value |
| --- | --- |
| **Title** | 2026 Q2 Alignment — single hypothesis, decision date, off-ramp |
| **Status** | Draft — unsigned |
| **Date drafted** | 2026-05-23 |
| **Author A** | `<<< FILL IN: maintainer — name + handle >>>` |
| **Author B** | `<<< FILL IN: collaborator — name + handle >>>` |
| **Supersedes** | none (new) |
| **Linked** | `brain/24_edge_validation_criteria.md` (kill/pass defaults), `brain/25_horse_race_protocol.md` (pre-registration), `brain/16_edge_proof_mvp_build_plan.md` (scope) |

---

## 1. The one-sentence hypothesis

Before Q2 closes, the team must commit to **one** falsifiable hypothesis about
where, on this stack, a real edge plausibly exists. Picking three is the same
as picking zero — the point of this section is to force a choice.

Illustrative examples (DO NOT pick all three — these are here only to make the
*shape* of an acceptable hypothesis concrete):

1. **8-K events** — "A walk-forward classifier on 8-K item codes + same-session
   price impact has a deflated Sharpe ≥ X over the OOS window after 10 bps
   round-trip cost on thin single-names."
2. **Fed RSS** — "Deterministic Fed-RSS macro reactions in SPY/QQQ have a
   positive, t ≥ 2 expectancy after 2 bps cost across N ≥ 30 events in the
   selection window AND survive a +5 minute latency stress test."
3. **Sparse-coverage earnings** — "Among QQQ constituents with <K analyst notes
   in the prior 30d, an LLM tone read on the earnings 8-K produces a hit-rate
   ≥ 55% next-session move-direction in OOS."

```
<<< FILL IN: write ONE sentence. It must name (a) the event class,
              (b) the instrument universe, (c) the horizon,
              (d) the metric and threshold that would falsify it. >>>
```

**Rule:** if the sentence above contains the word "or", or names more than one
event class, it is not yet a hypothesis. Cut until exactly one falsifiable
claim remains.

---

## 2. The decision point

A pre-declared, **objective** trigger. Not "when it feels ready." The trigger
must be something a third party could verify from the repo state alone (a
merged PR, a completed backfill, a logged OOS run).

```
<<< FILL IN: concrete trigger,
              e.g. "after PR #XX merges and events backfill completes,
                    run OOS once" >>>
```

Companion fields (also FILL IN):

- **Decision date (hard deadline):** `<<< FILL IN: YYYY-MM-DD — at most 4
  weeks from sign-off >>>`
- **Who runs the OOS:** `<<< FILL IN: name >>>`
- **Who countersigns the result:** `<<< FILL IN: name >>>`
- **Where the OOS artifact lives:** `<<< FILL IN: path or PR # >>>`

The OOS is run **once**. No re-runs after seeing the number. See `brain/25`
Section 5.

---

## 3. Pre-declared kill/pass thresholds

These numbers are committed **before** the OOS is run. The defaults shown
below come from `brain/24_edge_validation_criteria.md` and are a starting
point only — the row marked `<<< FILL IN >>>` is the value this Q2 alignment
adopts. If the team adopts the `brain/24` default unchanged, write the same
number in the FILL IN column and initial — that is still an explicit choice.

| Metric | `brain/24` default | This Q2 commitment |
| --- | --- | --- |
| OOS Sharpe (deflated) | not specified in `brain/24` — propose ≥ 1.0 | `<<< FILL IN >>>` |
| Hit rate | ≥ 55% | `<<< FILL IN >>>` |
| t-stat | ≥ 2.0 | `<<< FILL IN >>>` |
| Sample size N | ≥ 30 events per bucket/horizon | `<<< FILL IN >>>` |
| Cost assumption | 2 bps SPY/QQQ · 10 bps thin single-name · options off | `<<< FILL IN >>>` |

Pass = **every** row meets the committed value. Kill = any row fails. No
partial-credit conclusions. No "directionally encouraging" language in the
writeup if a threshold misses.

---

## 4. Off-ramp on failure

If the OOS fails any threshold in Section 3, the team commits in advance to
**one** of the following. Circle one. Picking now removes the temptation to
sandbag the threshold later.

- (a) **Personal trading at small size.** Wind the brain down to a personal
  account at sub-pilot size; treat as paid education; halt further engineering
  spend on this hypothesis.
- (b) **Negative-result writeup + portfolio asset.** Publish a clean
  negative-result post (data, methodology, what didn't work) and treat the
  repo as a portfolio artifact. No further trading.
- (c) **Explicit constraint: NO SaaS pivot.** Repurposing a failed quant edge
  into a "platform for traders" or "newsletter" is hereby pre-declared
  off-limits. Failure means the hypothesis is dead, not that the business
  model rotates.

```
<<< FILL IN: circle exactly one of (a), (b), (c). >>>
```

**Rule:** writing "we'll decide later" here is equivalent to choosing (c) and
then violating it in 8 weeks. Pick now.

---

## 5. In-scope / Out-of-scope (four weeks to decision)

Pre-populated from `brain/16` build plan. Edit only by striking through —
**no additions** between sign-off and the decision date. Anything not on the
IN list must wait.

### In scope

- Walk-forward edge gate (cross-validated OOS harness).
- Events backfill (the historical replay corpus that the gate consumes).
- Leaderboard protocol surfacing (`brain/25` pre-registration visible from the
  leaderboard view, with deflated-composite as the selection metric).

### Out of scope

- Dashboard polish beyond the protocol banner.
- Multi-asset universe expansion (stay in current SPY/QQQ + top-N).
- Ensemble brain / brain-of-brains.
- Additional ingestion adapters (no new vendors, no new feeds).
- FinBERT, VADER, or any additional NLP layer.
- Live trading (paper only; live remains gated per `brain/24` deployment
  ladder).

---

## 6. Sign-off

Two commits, by two separate authors, on this branch. Each author fills in
their line in a **separate commit**. The PR that contains this file does not
merge until both lines are non-empty and both commits are present.

```
Author A signature:  <<< FILL IN: name + date — commit by Author A only >>>
Author B signature:  <<< FILL IN: name + date — commit by Author B only >>>
```

**Hard rule:** no PR in the open stack merges until both lines above are
filled by separate commits authored by the maintainer and the collaborator respectively.
