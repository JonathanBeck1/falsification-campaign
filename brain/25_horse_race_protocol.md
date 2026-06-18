> ⚠️ **UNSIGNED DRAFT — DO NOT REFERENCE.**
> This file is a pre-registration skeleton with placeholders
> (`<<< FILL IN >>>`). It is not the protocol of record until the maintainer
> counter-signs the companion `brain/26_alignment_2026Q2.md`
> AND locks the pre-registration commit hash in Section 6 below. **No other
> code, doc, or PR may cite this file as authority until that lock is in
> place.** Treat it as non-existent until then.

---

# 25 — Horse-Race Protocol (Pre-Registration)

| Field | Value |
| --- | --- |
| **Title** | Horse-race pre-registration — variant selection → OOS confirmation |
| **Status** | Draft — placeholders |
| **Date drafted** | 2026-05-23 |
| **Linked** | `brain/26_alignment_2026Q2.md` (Q2 thresholds), `brain/24_edge_validation_criteria.md` (cost & gate defaults), `src/trader/signals/variants.py` (variant universe), `src/trader/scoring/leaderboard.py` (selection metric) |

This document is a **pre-registration**, not a postmortem. Every field below
must be locked **before** the selection metric is computed on the selection
window. Filling in any value retroactively voids the run.

---

## 1. Variant universe

The horse race is conducted over **exactly** the variants enumerated below,
drawn from `src/trader/signals/variants.py::all_phase_variants()` as of the
pre-registration commit (Section 6). Today this is **N = 16** variants across
Phases 1–4. If `all_phase_variants()` grows after the lock, the new entries
do **not** join this race.

### Phase 1 — VIX regime + Hybrid (6)

1. `VIXRegimeConservative`
2. `VIXRegimeAggressive`
3. `HybridHaikuConservative`
4. `HybridHaikuAggressive`
5. `HybridGPT4oMiniConservative`
6. `HybridGPT4oMiniAggressive`

### Phase 2 — Deterministic Fed/macro (2)

7. `MacroEventConservative`
8. `MacroEventAggressive`

### Phase 3 — LLM earnings-tone over 8-Ks (4)

9. `EarningsToneHaikuConservative`
10. `EarningsToneHaikuAggressive`
11. `EarningsToneGPT4oMiniConservative`
12. `EarningsToneGPT4oMiniAggressive`

### Phase 4 — Classical + sentiment-momentum baselines (4)

13. `ClassicalConservative`
14. `ClassicalAggressive`
15. `SentimentMomentumConservative`
16. `SentimentMomentumAggressive`

> **Hard rule — no silent additions during selection.** Between the
> pre-registration commit (Section 6) and the end of OOS confirmation
> (Section 5), no variant may be added, renamed, removed, or have its
> internal dials retuned. Any such change voids the run and the race
> restarts from a new pre-registration. A variant present in
> `all_phase_variants()` but absent from this list is **out** of this race.

If the actual count at lock time differs from N = 16, update this section in
the **same commit** that fills Section 6.

---

## 2. Data windows

All three windows are wall-clock dates (UTC). They partition the available
event history into a selection window and a disjoint OOS window. There is no
overlap and no third "validation" peek.

| Window | Value |
| --- | --- |
| `selection_start` | `<<< FILL IN: YYYY-MM-DD — earliest event timestamp used for ranking >>>` |
| `selection_end / oos_cutoff` | `<<< FILL IN: YYYY-MM-DD >>>` |
| `oos_end` | `<<< FILL IN: YYYY-MM-DD — last event timestamp eligible for OOS confirmation >>>` |

**Build-plan default proposal (not yet adopted):**

- `selection_start` = earliest event in the backfilled corpus.
- `oos_cutoff` = **today − 90 days**.
- `oos_end` = today (or the last fully-settled trading day).

The 90-day OOS buffer is a starting point only. Mark `<<< FILL IN >>>` and
finalize before lock.

**Rule:** the selection window is for ranking only. The OOS window is **never
touched** by any tuning, threshold-setting, or variant-shortlisting step.

---

## 3. Selection metric

Variants are ranked **on the selection window only** using:

- `composite_score` (defined in `src/trader/scoring/leaderboard.py`) as the
  human-readable headline metric.
- `deflated_composite` as the **ranking** metric — a deflation of
  `composite_score` that penalizes multiple-comparisons risk across the N
  variants in this race (sample-size and variant-count adjusted).

> **Ranking rule:** the variant with the **highest `deflated_composite`** on
> the selection window is the top-1. Ties are broken by raw `composite_score`,
> then by Sharpe, then alphabetically by variant name.

> **Implementation note (pre-lock):** if `deflated_composite` is not yet
> implemented in `leaderboard.py` at lock time, the pre-registration commit
> (Section 6) MUST be preceded by a PR that adds it. Locking this protocol
> against a not-yet-implemented metric is forbidden.

---

## 4. Pass condition for top-1 → OOS

The top-1 variant advances to OOS confirmation **only if** its selection-
window metrics clear the floor below. Otherwise the race ends here with no
OOS run.

| Gate | Value |
| --- | --- |
| Selection-window deflated Sharpe floor | `<<< FILL IN: e.g. ≥ 1.0 — must be set BEFORE selection metric is computed >>>` |
| Selection-window sample size N | `<<< FILL IN: ≥ 30 per `brain/24`, or higher >>>` |
| Selection-window hit rate | `<<< FILL IN: ≥ 55% per `brain/24`, or higher >>>` |

If the top-1 fails the floor: no OOS run, no second-place fallback. The
hypothesis is killed per `brain/26` Section 4 off-ramp.

---

## 5. OOS confirmation rules

If and only if Section 4 passes, **exactly one** variant — the top-1 from the
selection ranking — is run against the OOS window.

- **One variant. One run. One number.** No re-runs, no re-fits, no parameter
  nudges between selection and OOS. The OOS code path is whatever was on
  disk at the pre-registration commit hash.
- **Pass condition:** OOS metrics meet **every** threshold committed in
  `brain/26_alignment_2026Q2.md` Section 3 (deflated Sharpe, hit rate,
  t-stat, sample size N, under the committed cost assumption).
- **No re-selection on failure.** If OOS fails, the team does NOT walk back
  to the selection window, pick the #2 variant, and try again. That is
  p-hacking by another name. The hypothesis is killed per `brain/26`
  Section 4 off-ramp.
- **No threshold revision after seeing the OOS number.** The thresholds in
  `brain/26` Section 3 are frozen by the sign-off there. Discovering after
  the fact that the OOS Sharpe was "almost" passing is not a pass.

---

## 6. Pre-registration lock

This protocol is in force only when **all** of the following are true:

1. Sections 1–5 above contain no remaining `<<< FILL IN >>>` markers.
2. `brain/26_alignment_2026Q2.md` Section 6 has the maintainer's signature
   committed.
3. The commit that fills Section 6 below locks the pre-registration hash before
   any result exists.

```
Pre-registration commit hash:  <<< FILL IN: full 40-char SHA of the commit
                                            that locks this protocol >>>
Locked on (date, UTC):         <<< FILL IN: YYYY-MM-DD >>>
Author A acknowledgement:      <<< FILL IN: maintainer — name + date >>>
Author B acknowledgement:      <<< FILL IN: collaborator — name + date >>>
```

Any code, doc, run output, or PR that cites this protocol before this
section is fully filled is citing a non-document. The horse-race tooling
should refuse to emit "pre-registered" badges until the hash above is
non-placeholder and present in `git log`.
