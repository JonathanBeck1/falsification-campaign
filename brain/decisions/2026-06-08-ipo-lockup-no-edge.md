# Decision: IPO lock-up expiry has no tradeable edge (v1 killed)

Date: 2026-06-08
Status: decided. Bucket killed at v1; do NOT proceed to v2 (convexity).
Owner: Jonathan (via Claude Code).

## Context: two stale assumptions this note corrects

1. **Premium-selling is falsified.** `brain/28` still frames the active strategy
   as "sell defined-risk SPY iron condors." Cross-regime testing killed the
   entire premium-selling family (iron condor, put-credit-spread, VRP-gated) on
   QQQ — no edge under any tuning, crushed by buy-and-hold. The active direction
   is no longer premium selling.
2. **New direction = catalyst-driven convexity.** Edge is in *analysis*, not
   structure: detect a rare, dated, forced-supply catalyst and express it with
   defined-risk long options. IPO lock-up expiry was the cleanest first test
   (known date ≈ IPO + 180d; mechanical insider/VC supply unlock).

## What we tested

Pre-registered (`research/lockup_expiry_study_preregistration.md`, written before
data): do liquid recent-IPO names show a negative market-adjusted abnormal
return and/or elevated realized vol around lock-up expiry, beyond a placebo
window, out-of-sample?

- Universe: genuine first-time IPOs 2019–2025 from SEC EDGAR (424B4/424B1 ∩
  recent S-1/F-1 ∩ no prior 10-K ∩ non-SPAC). 1558 IPOs, 1066 with tickers.
- Prices: yfinance daily, split-adjusted. SPY as the market control (beta=1).
- Metrics: CARs over [-5,-1], [-1,+1], [0,+5], [0,+10], [0,+21]; realized-vol
  ratio (post/pre); placebo at −60 trading days; OOS split at lock-up year 2022.
- Liquidity filter: median dollar volume ≥ $5M/day → **N = 302**.

## Result: ❌ FAIL (clean null)

| window | mean % | t-stat | note |
|---|---|---|---|
| car_m5_m1 | −1.03 | −1.75 | mild pre-expiry dip, below threshold |
| car_0_p5  | +1.17 | +1.53 | rebounds *up* after expiry |
| car_0_p21 | +0.93 | +0.82 | slightly positive, indistinguishable from 0 |
| vol_ratio | 1.195 | +1.27 | but placebo vol_ratio = 1.170 → not lock-up-specific |

- The primary horizon CAR is **positive and insignificant** — opposite the thesis.
- The vol bump is **not lock-up-specific** (placebo ≈ identical).
- The only whiff (−1% into expiry) is below threshold and reverses after.

## Interpretation

The classic Field-Hanka (2001) ~1–3% negative lock-up abnormal return has
**decayed to nothing** in the modern, liquid sample — exactly what "public since
2001, fully anticipated, arbitraged" predicts. The lock-up date is on every
calendar; supply is pre-positioned; there is no surprise left to harvest.

This is the **third independent confirmation** of the project's core finding:
known structures and known catalysts are priced in (condor → no edge; VRP →
selection bias; lock-up → decayed). Edge requires genuinely *differentiated*
analysis or information, not a catalyst everyone can see on a calendar.

## Decision

- **Do not run v2 (convexity / long puts) on lock-ups.** v1 fails the
  pre-registered kill criteria (|CAR| < ~1% and vol ratio not lock-up-specific);
  buying premium against a non-existent move would just pay theta.
- Keep the machinery. `trader.catalysts.{ipo_lockup,ipo_universe,lockup_study,
  prices}` + `scripts/run_lockup_study.py` are a reusable event-study harness for
  the next catalyst bucket.

## Next candidate buckets (same machinery, same pre-registration discipline)

Pick one and pre-register before testing:
- **Form-4 insider-cluster buying** (multiple insiders buying open-market) — the
  one insider signal with the most literature support.
- **Index add/delete** (S&P/Nasdaq reconstitution) — but heavily studied; expect
  decay.
- Honest prior on all of these: most will fail the same way. The value is the
  cheap, correct kill — and the small chance one bucket is genuinely
  under-analyzed.
