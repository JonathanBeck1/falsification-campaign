# Decision: Intraday QQQ lab disabled — data quality bug

Date: 2026-06-09
Status: lab disabled. The "intraday minute data" we extracted is NOT real QQQ
prices and the Sharpe 11 result is an artifact, not edge.

## What we built

`src/trader/mining/intraday_qqq.py` extracts minute-level QQQ underlying prices
from the options lake's `underlying_price` column, computes daily intraday
features (overnight return, open-to-close, lunchtime mean-rev, etc.), and feeds
17 variants through the mining lab. First run showed Sharpe 6-11 on `gap_fade`
and the Haghani overnight variants — completely impossible for QQQ.

## What went wrong

The `underlying_price` field in the ThetaData options lake is **put-call-parity
derived**, not real QQQ spot. Per ThetaData docs: *"Default parity works on
ThetaData Options Value; stock requires stock-data entitlement."* This means:

1. The "spot" at each minute is computed from option bid/ask mid-prices via
   parity arithmetic across the chain.
2. Per-contract values vary widely (e.g. on 2024-09-19 09:30:00: min=469.64,
   max=535.79, median=483, range = $66 around true ~$478).
3. **At the open minute, many contracts have stale quotes carried over from
   yesterday's close**, biasing the implied spot low.
4. **At the close minute, the closing auction prints aren't in option quotes**,
   so spot is biased high relative to the next morning's actual open.

## Evidence the data is broken

- **Pre-median-fix**: `max()` aggregation picked the largest stale outlier per
  minute → fake +14% overnight gaps → Sharpe 11.
- **Post-median-fix**: median is more robust but still produces -25 bp/day mean
  overnight return → cumulative -98.75% over 1612 days. QQQ's REAL overnight
  contribution should be POSITIVE (~50%/yr per Haghani).
- The strategy `gap_fade` Sharpe went UP after the fix (6.06→6.53 IS, 10.21→11.68
  OOS), because the bias is still there in a different direction.
- A reliable QQQ minute series would need yfinance 1-min (only 60 days
  available) or a paid stock-data subscription on ThetaData.

## Honest action

- Removed `output/catalysts/intraday_lab.json` so the dashboard doesn't show
  contaminated results.
- Kept the code (`src/trader/mining/intraday_qqq.py`) and tests for future
  refactor — the *strategy* logic is fine; only the data source is broken.
- Counted as kill: no Sharpe-claiming result trustworthy until a real spot
  source is wired in.

## Lesson

The falsification machine actually caught this — Sharpe 11 was the obvious red
flag. Data quality bugs are insidious because they look like alpha. The
deflated-Sharpe gate can't catch them; only sanity checks like "QQQ's overnight
shouldn't be Sharpe 11" can. **Always sanity-check 'too good to be true'
results against known benchmarks** before adding to the survivor count.

## What it would take to revive

1. Get real QQQ minute spot from a separate source (e.g. polygon.io free tier,
   IEX Cloud, or running a separate ThetaData stock-data subscription).
2. Cross-check overnight_ret against yfinance daily open/close to confirm the
   minute source is unbiased.
3. Re-run the lab. Honest expectation given Haghani: a few real low-Sharpe
   survivors (overnight effect at maybe Sharpe 0.5-1) that get killed by costs.
