# Decision: product_news__up KILLED by matched-control test — campaign now 18-for-18

Date: 2026-06-10
Status: the last surviving Phase 2 candidate is dead. No watchlist candidates remain.

## Why the pooled baseline wasn't enough

The Phase 2 baseline check used a POOLED baseline (+2.39% across all 1,492
events). But drift is wildly heterogeneous by ticker and year: NVDA/TSLA in
2020-2023 drift enormously vs SPY; JPM doesn't. If a cohort clusters in
high-drift (ticker, year) cells, it beats the pooled baseline without any
catalyst effect. product_news__up clusters exactly there:

- **TSLA: 23 of 48 events. NVDA: 9 of 48.**
- **2020 alone: 24 of 48 events** (TSLA's +700% year).

## The test (pre-registered, seed=7)

Per-event baseline = mean CAR[+1,+21] over ALL eligible quiet days for the
SAME ticker in the SAME calendar year (excluding ±5 trading days around any
catalog event for that ticker). Plus 2,000 placebo cohorts with identical
(ticker, year) composition. Gates: net |t|≥2 AND permutation p<0.05.

## Result

| metric | value |
|---|---:|
| raw cohort CAR[+1,+21] | +9.26% |
| matched (ticker, year) baseline | **+9.12%** |
| **net drift** | **+0.14% (t=+0.07)** |
| permutation p-value | **0.473** |
| placebo cohort mean / 95th pct | +9.17% / +11.70% |

The observed cohort mean sits at the 47th percentile of its own placebo
distribution — i.e. a random same-(ticker, year) cohort does this half the
time. There is NOTHING here.

## Classifier-leak probe (bonus diagnostic)

High-confidence events: raw +12.69% vs med/low +7.70% — looks like the LLM
classifier's confidence "predicts" drift. But the NET values are +1.14% vs
−0.31%: the confidence gap was ALSO composition (the classifier is more
confident about famous TSLA/NVDA product events, which sit in high-drift
cells). Consistent with hindsight leakage in classification confidence, fully
absorbed by the matched control.

## Lessons (additions to standard methodology)

1. **Pooled baselines are insufficient.** Any event-study CAR claim must use a
   matched (ticker, year) control or a composition-matched permutation test.
   The pooled baseline killed 4 of 5 fake survivors; the matched control
   killed the 5th.
2. **LLM classifiers leak hindsight.** A model labeling historical events
   knows what happened afterward; cohorts it selects inherit look-ahead bias
   that window discipline cannot remove. Matched controls absorb this too.
3. Files: `scripts/run_product_news_control.py`,
   `research/product_news_control_report.md`,
   `output/catalysts/product_news_control_results.json`.

## Campaign scoreboard

18 rigorous tests, **18 kills**. No watchlist candidates remain. The durable
asset is the falsification machine itself: pre-registration, OOS splits,
friction realism, pooled baseline, and now matched-control permutation as a
mandatory final gate.

## Action

- Remove `product_news__up` from the watchlist (supersedes the watchlist note
  in `2026-06-10-phase2-mega-cap-beta-trap.md`).
- Matched-control permutation becomes a REQUIRED gate for any future
  event-study survivor claim.
