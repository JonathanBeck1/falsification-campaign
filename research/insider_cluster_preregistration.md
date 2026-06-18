# Pre-registration — Insider-Buy Clusters as a Forward-Return Signal

**Status:** pre-registered BEFORE running. Written to be falsified.
**Author:** skeptical quant researcher. **Date:** 2026-06.

## Question

When **several distinct insiders of the same issuer file Form-4 open-market
PURCHASES (transaction code `P`) within a short window** (a "cluster"), does the
stock earn a positive **market-adjusted** cumulative abnormal return (CAR) over
the following 1/3/6/12 months?

## Honest prior

Insider buying is the single best-documented insider signal in the academic
literature (Lakonishok–Lee, Cohen–Malloy–Pomorski "routine vs opportunistic",
Jeng–Metrick–Zeckhauser). Clusters (multiple insiders, "conviction buys") are
the strongest sub-variant. BUT: the effect is decades-old, widely published, and
sold by commercial screens (e.g. cluster-buy newsletters). Anything well-known
is likely arbitraged down. **Base-rate expectation: a small positive CAR at best,
quite possibly null after a placebo and OOS split.** A large, clean, significant
result is more likely a survivorship/look-ahead bug than real alpha — we will
treat it with suspicion, not celebration.

## Hypotheses (directional, pre-registered)

* **H1 (primary):** Cluster events have mean market-adjusted CAR over `[0,+63]`
  trading days (~3 months) > 0 with `|t| >= 2`.
* **H0 (null):** Cluster CAR is indistinguishable from 0 and/or from placebo.

Secondary horizons reported for context: `[0,+21]`, `[0,+126]`, `[0,+252]`.

## Definitions

* **Open-market purchase:** Form-4 non-derivative transaction with `Code == 'P'`.
  We explicitly EXCLUDE `A` (award/grant), `M` (option exercise), `C`
  (conversion), `G` (gift), `F` (tax), `S` (sale). Only `P` counts.
* **Distinct insider:** unique reporting-owner name (normalized, upper-cased,
  whitespace-collapsed) for the issuer. A single insider buying the same name on
  many days is NOT a cluster, no matter how many tickets.
* **Cluster:** for one issuer (keyed by issuer CIK), `>= K` distinct insiders
  each with at least one `P` whose transaction dates all fall inside a rolling
  window of `<= CLUSTER_WINDOW_DAYS = 30` calendar days.
  - Primary: **K = 2**. Stricter robustness arm: **K = 3**.
* **Event date (t0 anchor):** the LAST (latest) buy transaction date in the
  cluster. Rationale: a follower cannot act until the final qualifying buy is on
  the tape; anchoring on the last buy avoids look-ahead and is the conservative
  entry. (Form-4 must be filed within 2 business days, so the public-knowledge
  date is close to the transaction date; we anchor on the transaction date and
  note the ~2-day reporting lag as a small optimism we do NOT correct for — a
  realistic follower is slightly later, so our CAR is, if anything, generous.)
* **De-duplication of clusters:** once a cluster fires for an issuer, subsequent
  buys within `MERGE_DAYS = 30` calendar days of the event date are absorbed
  into it (no overlapping double-counting of the same buying wave).

## Metric — market-adjusted CAR vs SPY (matches house style)

For each event, abnormal return `AR_t = stock_ret_t - SPY_ret_t` (beta = 1, the
same conservative simplification used in `lockup_study.py`). CAR over a window
`[0, +h]` is the sum of daily `AR_t` from t0 through t0+h (inclusive), in trading
days. SPY is reindexed/forward-filled onto the stock's trading calendar. We use
adjusted closes (yfinance `auto_adjust=True`) so splits/dividends are handled.

Windows (trading days from t0):
`car_0_p21`, `car_0_p63` (**PRIMARY**), `car_0_p126`, `car_0_p252`.

An event is included only if its full `[0, +252]` window of trading data exists
for the stock. (We require the longest window so the same N is used across all
horizons — no horizon-dependent survivorship.)

## Sample (declared in advance — exactly what we will scan)

The Form-4 universe is enormous (~1,000–1,500 filings PER DAY). Parsing every
filing for 2019–2023 is infeasible in this budget (~0.25 s/filing parse). We
therefore pre-register a **bounded, date-stratified sample**:

* **Filing-date sample:** the **first 4 calendar days of each month** for
  **2019-01 through 2023-06** (so that 12-month forward returns through ~2024-06
  exist for every event). That is 54 months × 4 days = **216 scanned filing-days**.
  This is a systematic (not cherry-picked) stratified sample across the whole
  period and all sectors/issuers that filed on those days.
* For each scanned day we parse **all** Form-4 filings, keep every `P`
  transaction, then build clusters per issuer over the 30-day window.
* yfinance purges delisted tickers; we will COUNT and report how many cluster
  issuers drop out for missing/short price history rather than hiding them.
  (Delisting-driven dropout biases the survivors UP — a known optimism we flag.)

We freeze the universe definition here. We will NOT expand the sample after
seeing results, and will NOT add/drop windows or change K after the fact.

## Controls

1. **Placebo.** For each cluster issuer, draw a random NON-cluster "pseudo-event"
   date for the same name (uniformly within that name's available price window,
   excluding ±30 trading days around any real cluster). Same CAR computation.
   The real effect must beat the placebo's primary CAR. This nets out
   "small-cap names that happened to drift" from "the cluster timing matters."
2. **Out-of-sample split.** Early = event year **2019–2021**, Late = **2022–2023**.
   The primary CAR must keep the **same sign** in both halves.

## Pre-registered GATE (ALL must pass)

1. **N >= 30** cluster events (primary K=2).
2. **Primary CAR `car_0_p63` mean > 0 with `|t| >= 2`.**
3. **Beats placebo** on the primary window (real mean > placebo mean).
4. **OOS sign stable** — `car_0_p63` mean has the same sign in 2019–2021 and
   2022–2023.

If any fails → **the idea is killed** and reported as a null. Consistent with
house culture (iron condors, VRP, IPO lock-up, broad CEF-follow, SPAC trust-arb
were all killed), a clean null is a successful, publishable outcome.

## Things that would make us DISTRUST a "pass"

* Effect concentrated in micro-caps with un-tradeable liquidity.
* Effect that vanishes when anchoring on filing date instead of transaction date.
* Huge CAR driven by a handful of multi-bagger survivors (delisting bias).
* t-stat inflated by overlapping events on correlated small-caps (we do NOT
  correct for cross-sectional correlation; an honest "pass" would need a
  cluster-robust SE follow-up before any capital).
