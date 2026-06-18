# Pre-registration: the index-rebalance effect (S&P 500 additions / deletions)

Status: **pre-registered before running.** Written 2026-06-09. Falsify-first.

## Question

Do S&P 500 index **additions** earn positive market-adjusted abnormal returns
(and **deletions** negative) around the membership change, and **has the effect
decayed** over 2010–2025?

## Honest prior (what the literature says)

The index-inclusion effect was large in the 1980s–90s: Shleifer (1986) and
Harris–Gurel (1986) found a permanent/temporary price pop of ~3% on S&P 500
additions, consistent with downward-sloping demand curves and index-fund buying
pressure. But subsequent work (Bennett–Gerasymenko, Greenwood, Patel–Welch, and
practitioner studies) documents that the effect has **largely decayed or
disappeared post-2000**: the announcement is now anticipated and front-run by
arbitrageurs, index funds use sampling/transition trading, and the float-adjusted
methodology change (2005) plus the rise of passive AUM cut both ways. **My prior
is therefore a weak-to-null effect, weaker in the recent sub-sample.** A clean
null here is a *successful* falsification, not a failure.

## Data sources and their reliability (scouted before pre-registering)

1. **Index changes (the event list).** Source:
   `fja05680/sp500` GitHub repo, file *"S&P 500 Historical Components & Changes
   (Updated).csv"* — a maintained, daily-ish series of **full constituent
   snapshots** from 1996 to present (2,712 snapshot dates through 2026-06-02).
   We derive add/delete **events** by diffing consecutive snapshots: a ticker in
   snapshot `t+1` but not `t` is an *addition* dated `t+1`; the reverse is a
   *deletion*. Cross-checked against the repo's independent
   `sp500_changes_since_2019.csv` event file — the two agree on essentially every
   2019 change. ~20–30 adds/dels per year, ~400 events 2010–2025.
   - **Reliability: good** for the *fact and date of membership change*, but with
     two caveats that are pre-registered limitations, not surprises:
     - **The snapshot date is the EFFECTIVE date, not the ANNOUNCEMENT date.**
       S&P typically announces ~1 week (≈5 trading days) before effective. We
       therefore treat t0 = effective date and place a pre-effective window
       `[-5,-1]` to capture the announcement-driven run-up. We CANNOT cleanly
       separate announce-day from effective-day with this source; this is stated
       as a wall.
     - Snapshot granularity / occasional date attribution can be off by 1 trading
       day. The windows ([-5,-1],[-1,+1],[0,+5],[0,+21]) are wide enough to be
       robust to ±1 day.

2. **Prices.** `yfinance`, auto-adjusted daily closes; SPY as the market proxy.
   - **Known wall (verified in scouting):** yfinance **purges acquired/delisted
     tickers**. A large share of deletions are caused by M&A (the deleted company
     is acquired; only the acquirer's ticker survives) — these return **zero rows**
     (verified: DWDP, LLL, RHT all empty). Deletions that survive as standalone
     companies (relegated for size/liquidity, e.g. PCG, GT) DO have data.
     **Consequence:** the deletion sample will be biased toward relegation/
     survivor deletions and will be smaller than the true count. **We count
     adds-with-data, dels-with-data, and dels-dropped-for-missing-data and report
     them explicitly.** Additions are alive by construction, so they are
     essentially complete.
   - **Glitch guard (pre-registered):** yfinance occasionally returns an
     unadjusted split day or a near-zero bad print, producing a single-day
     abnormal return of thousands of percent that would dominate a mean. Any event
     with a single-day |market-adjusted return| > 0.75 (75%) inside the widest
     window is **dropped and counted as missing** (no S&P 500 constituent moves
     75% in one day for real). Calibrated on the data this catches exactly one
     2010-2025 addition (CBE, 2011, a +65,000% spike). Reported as a dropped count.

## Method

* **Events.** Two separate event sets: ADDITIONS and DELETIONS, each a list of
  `(ticker, effective_date)`.
* **t0** = first trading day on or after the effective date.
* **Abnormal return** = stock daily return − SPY daily return (market-adjusted,
  **beta = 1**, matching the house lockup/cef studies — a deliberate conservative
  simplification, no estimation-window beta).
* **CAR windows** (trading days relative to t0, inclusive):
  - `car_m5_m1` = [-5,-1]  — pre-effective run-up (captures the announcement,
    which lands ~1wk before effective).
  - `car_m1_p1` = [-1,+1]  — the change itself.
  - `car_0_p5`  = [0,+5].
  - `car_0_p21` = [0,+21]  — **primary horizon** (~1 month, post-inclusion drift /
    reversal).
* **Aggregation.** Mean, median, %positive, and a one-sample t-stat vs 0 per
  window, across events.
* **OOS / decay split.** EARLY = effective date in 2010–2017; RECENT = 2018–2025.
  The decay test explicitly compares the primary-window mean across the two.

## Pre-registered gate (ALL must hold) — for ADDITIONS

1. **N ≥ 30** additions with usable data.
2. **Primary CAR positive with |t| ≥ 2**: `car_0_p21` mean > 0 and |t| ≥ 2.
   (For DELETIONS, the symmetric requirement is mean < 0 with |t| ≥ 2; reported
   but additions are the headline gate.)
3. **Same sign OOS**: `car_0_p21` mean has the same sign in EARLY and RECENT.
4. **Decay reported** (always, regardless of pass/fail): the EARLY vs RECENT
   primary-window means are tabulated and we state whether the effect is larger
   early (the predicted decay) or not.

If the gate fails — in particular if the effect is null in RECENT — that is a
**confirmation of the decay prior and a successful kill**, reported as such.

## What would change my mind / threats to validity (stated up front)

* If additions show a large positive `car_m5_m1` but flat `car_0_p21`, that is the
  classic "priced-in by the effective date, all the move is in the pre-window"
  pattern — *not* a tradable post-effective edge.
* Effective-date-only timing means we likely **understate** any announcement pop;
  if even with that handicap additions are flat/negative post-effective, the
  tradable-edge conclusion is robust.
* yfinance survivorship on deletions means a flat/positive deletion CAR could be a
  selection artifact (only survivors remain). We will not over-read the deletion
  side.
