# Decision: CEF discount-capture FALSIFIED with real (Tiingo) data

Date: 2026-06-09
Status: the last surviving lead is killed. Pre-registered gate FAILED; the
encouraging-looking untilted number is an artifact, not an edge.

## What we ran
The real survival backtest (`scripts/run_cef_survival.py`) with a Tiingo key, so
the resolved/delisted winners are finally priced (81 of 82, incl. ASA/BNY/BIGZ/
the Tortoise energy funds that yfinance purges). Buy each Saba 13D target the day
after filing, hold to resolution (or ~2yr cap), realized return minus PCEF.

## Result
- Untilted (N=81): mean excess **+10.5%, t=+2.45**, but **median +0.9%, 52% positive**.
- Tilted muni+fast-sponsor (N=47): +5.4%, t=0.96, median **-9.25%**.
- **Pre-registered gate FAILED**: the tilt is insignificant AND underperforms the
  untilted basket. The muni+fast-sponsor tilt hypothesis is falsified.

## Why the +10.5% is a mirage (not an edge)
1. Median is ~0 and only 52% positive — the mean is a right-tail of outliers.
2. The big winners are ASSET-CLASS BETA vs a mismatched benchmark: ASA +209% =
   the gold rally; NDP/TTP/NTG/CTR (+57-99%) = the energy/MLP rally. PCEF is a
   broad-CEF proxy, so sector drift masquerades as alpha.
3. BNY shows +224% TARGET return on a NY MUNICIPAL fund over 2.4y — physically
   impossible; a Tiingo adjustment glitch (same class as the CBE index-study
   glitch). It inflates the mean.
4. t-stat inflated by those outliers AND cross-sectional correlation (many
   same-sponsor muni clones resolving in the same rate cycle; no cluster-robust SE).
5. After ~1% CEF frictions a median of +0.9% over two years is ~zero.

## Verdict
The falsification machine caught a +10.5%/t=2.45 result — at the hardest moment —
and showed it is outliers + benchmark mismatch + a data glitch, not edge. The CEF
discount-capture lead joins the others. SEVEN ideas tested (condor, VRP, IPO
lock-up, broad CEF-follow, SPAC-arb, index-rebalance, CEF survival); all
falsified under proper scrutiny. No systematic edge — now measured, not estimated.

## What a v2 would need (to even reopen it)
Asset-class-matched benchmarks (muni-CEF index for munis, energy for energy, not
one broad ETF), a single-day |return| glitch guard, cluster-robust/bootstrap SEs,
and the actual liquidation cash-out (not last traded mark). Even then, the median
~0 says the broad effect isn't there. Not worth reopening without a new idea.
