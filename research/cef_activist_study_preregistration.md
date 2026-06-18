# Pre-Registration: Following Saba's Activist 13D into Closed-End Funds

> Status: pre-registered, written **before** running the study. Locks the
> hypothesis, the follower-capturable window, the controls, and the kill
> criteria so we cannot rationalize a biased result (as we nearly did with VRP).

## Why this exists

Game 2 = capacity-constrained niches where being small is an *advantage*.
Closed-end-fund (CEF) discount activism is live: Saba Capital (Boaz Weinstein)
is the dominant activist, forcing tenders / open-endings / liquidations that
narrow CEF discounts to NAV. A small player cannot *run* a campaign, but can
**follow** the activist: Saba's stakes are public in SC 13D filings (reachable
via our EDGAR harness).

## The sharp, falsifiable question

A 13D is **public**. Efficient markets say the discount-narrowing should be
priced into the announcement-day move, leaving nothing for a follower who can
only act *after* the filing is public. So:

> Does buying a CEF the day **after** Saba's initial SC 13D becomes public earn
> a positive excess return vs the broad CEF market over 1–12 months — or is the
> effect already gone (priced in the pre-disclosure run-up and the
> announcement-day pop)?

## Honest prior

Activist-CEF is real and live, but crowded, and 13D disclosure is public. My
prior: most of the gap-closing is captured by Saba and fast players **before**
the filing is public; the **follower-capturable** post-disclosure drift is
likely **weak or zero**. A clean positive post-13D drift would be the surprising
(and valuable) result. Expect to reject, and treat a strong pass with suspicion.

## Data (all confirmed feasible)

- **Events**: Saba (CIK 0001510281) initial **SC 13D** on CEFs, 2022-01-01 ..
  2025-06-30 (so +12mo forward exists by now), via EDGAR full-text search.
  Earliest SC 13D per subject CIK (the campaign start, not 13D/A amendments).
  ~82 campaigns before data filters.
- **Prices**: yfinance **adjusted** close (total return — essential for CEFs,
  which pay large distributions) for each target + the benchmark.
- **Benchmark**: **PCEF** (Invesco CEF Income Composite ETF) as the broad-CEF
  market proxy; **YYY** as a robustness check. This nets out CEF-market beta and
  general discount/asset-class moves **without needing per-fund NAV** (NAV is not
  freely available; CEFConnect is anti-bot, NAV pseudo-tickers are unreliable).

## Method

t0 = first trading day on/after the 13D file date. **Follower entry = t0+1**
(you can only act once the filing is public). Excess return = target total
return − PCEF total return.

Decompose the effect by window (this is the whole point):
- **Pre-disclosure run-up** `exc_pre` = excess over [-126, -1]. *Cannot* be
  captured (happens before the filing is public). Selection check.
- **Announcement pop** `exc_ann` = excess over [-1, +1]. Mostly *not* capturable
  by a public follower.
- **Follower-capturable drift** = excess from entry (t0+1) over the next
  21 / 63 / 126 / 252 trading days (`exc_1m/3m/6m/12m`). **This is the number
  that matters.**

## Pre-registered gate (ALL must hold)

- **N ≥ 30** campaigns with full price data.
- **Follower-capturable `exc_6m` > 0 with t-stat ≥ 2.0** (6-month is the primary
  horizon; activist catalysts resolve over quarters).
- Post-disclosure drift **exceeds the pre-disclosure run-up** (`exc_6m` from
  entry is not just a continuation of `exc_pre`).
- **Same sign across OOS split** (2022–2023 vs 2024–2025 campaigns).

## Pre-registered kill criteria

- Follower-capturable `exc_6m` ≤ 0 or |t| < 2.
- The entire effect sits in `exc_pre` + `exc_ann` (priced before a follower can
  act) — i.e. the post-disclosure drift is flat.
- Disappears or flips sign OOS, or is driven by < 5 funds.

## What each outcome buys us

- **Pass** → a reachable, capacity-constrained, *capturable* edge for a small
  shop. Advance to v2 (sizing, CEF execution friction, holding-period, which
  Saba targets resolve fastest).
- **Fail** → the activist alpha is real but *priced by disclosure* — you'd need
  to be the activist, not a follower. Cheap, correct kill; move to SPAC-arb base.

## Honest limitations (documented up front)

- PCEF is a *broad* CEF proxy; Saba's targets skew muni + equity, so the
  benchmark is imperfect (we report YYY as a robustness check and the raw,
  un-benchmarked return too).
- Total-return via yfinance auto-adjust folds distributions back in; CEF
  distribution timing can be lumpy. Treat magnitudes as approximate.
- Survivorship/listing gaps: funds that liquidated may have truncated price
  history (counted, not silently dropped).
