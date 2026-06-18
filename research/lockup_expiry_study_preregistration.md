# Pre-Registration: IPO Lock-Up Expiry as a Convexity Catalyst

> Status: pre-registered design, written **before** looking at the data.
> Purpose: lock the hypothesis, control, and kill criteria up front so we cannot
> later rationalize a selection-biased result into an "edge" (the mistake we made
> with the VRP gate). If the data does not clear the gate below, the bucket dies.

## Why this exists

We falsified the entire premium-selling family (iron condor, put-credit-spread,
VRP-gated) on QQQ. The project's conclusion: **edge lives in analysis, not
structure** — detect a rare, dated catalyst that creates forced supply, and
express it with defined-risk convexity (long puts) so we survive being early.

IPO lock-up expiry is the cleanest first test of that thesis:
- It is a **known date** (≈180 calendar days after the IPO), so timing — the
  thing news-momentum strategies lack — is given to us for free.
- It is a **forced-supply event**: insiders, VCs, and pre-IPO holders become
  free to sell, mechanically increasing float.
- It is **single-name and convex-friendly**: recent IPOs are high-vol, and the
  downside is dated, which is exactly when a long put is the right tool.

## Prior belief (stated honestly, before data)

The academic record (Field & Hanka 2001; Bradley et al. 2001; Brav & Gompers
2003) documents a **small but statistically significant negative abnormal
return (~1–3%)** and a **permanent jump in trading volume** around lock-up
expiry. So our prior is:

- There is *probably* a real underlying effect.
- BUT it has been public since 2001, so it is likely **partially priced in and
  decayed**, and the magnitude (~1–2%) is **small**.
- Therefore the binding question is **v2**: does the *options market underprice*
  this dated downside? A 1–2% drift is only tradeable as convexity if puts are
  cheap relative to the realized move. v1 just establishes whether the
  underlying effect still exists at all.

We should expect to **reject or barely-pass v1**, and treat a clean pass with
suspicion. A huge effect would more likely mean a data/selection bug than a
missed edge.

## Data

- **Events**: `trader.catalysts.ipo_lockup.build_ipo_lockup_events` — liquid US
  IPOs, `ipo_date` (424B4 proxy), `lockup_expiry_date = ipo_date + 180d`.
  Window: IPOs priced **2019-01-01 .. 2025-06-30** (so every event has ≥180d of
  post-lockup price history as of today, 2026-06-08).
- **Prices**: daily OHLC for each event ticker + SPY (market control), via the
  existing Alpaca/Yahoo adapters. Events whose ticker has no usable price
  history are dropped and **counted** (no silent loss).
- **Liquidity filter (pre-registered)**: keep only names with a median dollar
  volume ≥ $5M/day over the [-30,-10] pre-event window, so the result is not
  driven by untradeable micro-caps. Report N before and after the filter.

## Method — v1 (underlying only; prove the effect exists)

Event-time study in **trading days** relative to `lockup_expiry_date` (t=0):

1. **Market-adjusted abnormal return**: for each event compute the cumulative
   return of the stock minus SPY over windows:
   `CAR[-5,-1]` (run-up), `CAR[-1,+1]`, `CAR[0,+5]`, `CAR[0,+10]`, `CAR[0,+21]`.
2. **Realized-vol ratio**: realized vol over `[+1,+21]` divided by realized vol
   over a `[-40,-20]` pre-baseline (same stock).
3. Aggregate across events: mean & median CAR per window, % negative, **t-stat**
   (and a bootstrap CI), mean vol ratio.

### The control (this is the part that prevents self-deception)

The effect must be **lock-up-specific**, not just "recent IPOs drift down / are
volatile." Two placebo tests, both pre-registered:

- **Placebo dates**: re-run the identical event-time study for each name using a
  fake event date **90 trading days before** the real lock-up. The real-window
  effect must be **significantly larger** than the placebo-window effect.
- **Already-market-adjusted**: because CAR subtracts SPY, a generic "IPOs lag the
  market" story is partially netted out; the placebo test removes the rest.

## Pre-registered pass gate (v1)

Adapted from `brain/24_edge_validation_criteria.md`. ALL must hold:

- **N ≥ 30** liquidity-filtered events.
- Mean `CAR[0,+21]` is **negative** with **|t-stat| ≥ 2.0**, *or* mean vol ratio
  **≥ 1.25 with t-stat ≥ 2.0**.
- Effect **survives the placebo test** (real window materially exceeds placebo).
- Effect **survives an OOS split**: same sign and direction in both
  2019–2022 and 2023–2025 sub-samples (no parameter tuning across the split).

## Pre-registered kill criteria (v1)

Stop the bucket if any hold:

- Real-window effect is statistically indistinguishable from the placebo window.
- Effect vanishes (or flips sign) in either OOS sub-sample.
- Result is driven by < 5 outlier events (drop top/bottom 3 → effect dies).
- Mean |CAR[0,+21]| < ~1% AND vol ratio < 1.1 — too small to ever beat option
  premium, so v2 is pointless even if "significant."

## v2 — convexity (ONLY if v1 passes)

Then, and only then: test whether a **defined-risk long put** (e.g. ~30–45 DTE
spanning t=0, ~10–20 delta) bought ~5 trading days before expiry was underpriced
— i.e. did the realized move exceed the premium paid, net of spread/fees, across
events. This requires single-name options history (ThetaData backfill — a
separate, later data task) and reuses the hardened options engine for marking.
v2 has its own pre-registration; it is out of scope here.

## What a negative result buys us

If v1 dies, that is a **cheap, correct kill** of the cleanest catalyst in the
thesis — and strong evidence that the dated-supply idea is already arbitraged.
That is a real finding, not a failure. We report it and move to the next bucket
(Form-4 insider clusters; index-rebalance), reusing this exact machinery.
