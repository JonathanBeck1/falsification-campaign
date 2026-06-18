# T23 - Single-Name Earnings IV Crush Study Result

Pre-registration: `research/earnings_iv_crush_preregistration.md`.

## Run metadata
- Run at: 2026-06-17T15:49:58.243160+00:00
- Span: 2022-01-01 .. 2026-06-15
- Universe: 24 single names (24 contributed events)
  EXCLUDED AAPL/AMZN/NVDA (still collecting) and QQQ/SPY (indices).
- Trade: sell ATM front straddle (>= 5d tenor) at pre-earnings
  close, buy back at first post-earnings close. Spot anchored by put-call parity.
- Friction: cross the quoted bid/ask each leg + $2.60/straddle commission.
- IS = earnings year <= 2023, OOS = year > 2023

## Sample accounting
- Complete earnings straddle events: 414
- Events dropped (missing bracket/quote/glitch): 17
- Placebo (non-earnings) one-day straddles: 720

## PRIMARY: after-cost short-straddle return (fraction of spot)
- N events: 414
- Mean: -0.593% of spot
- After-cost t-stat: -3.61
- Median: -0.040%
- Win rate: 49.3%
- Sharpe (mean/std across events): -0.177
- Std across events: 3.342%

## IV overstatement decomposition (priced vs realized move)
- Mean priced move (straddle mid / spot): 7.059%
- Mean realized overnight move: 5.471%
- Mean crush gap (priced - realized): +1.588%
- Median crush gap: +1.922%
  (positive => pre-earnings IV overstated the realized move on average)

## Jump-variance check (is it compensated variance, not alpha?)
- Corr(after-cost P&L, realized move): -0.843
  (strongly negative => the losses ARE the big earnings gaps = compensated jump variance)

## Same-name non-earnings placebo (the ordinary short-vol carry)
- N windows: 720
- Mean after-cost return: -0.448%
- t-stat: -13.18
- Earnings premium over placebo: -0.146% (Welch t=-0.87)

## IS / OOS (decay check)
- IS  (<= 2023) mean: -0.397% (n=183, t=-1.61)
- OOS (>  2023) mean: -0.749% (n=231, t=-3.41)

## TAIL / loss distribution (catastrophic-tail report, MANDATORY)
- Worst single event: -23.22% (NFLX 2022-04-19)
- Loss events: 210/414 (50.7%)
- Sum of 5 worst events: -81.46% of spot
- Sum of ALL events: -245.59% of spot
- Mean excluding 5 worst: -0.401% (vs full -0.593%)
- Deaths dominate (full mean<=0 but positive ex-worst-5): False
- Bottom-5 (the deaths): NFLX 2022-04-19 -23.2%, AVGO 2024-12-12 -16.4%, META 2023-02-01 -14.3%, NFLX 2022-01-20 -13.9%, META 2024-02-01 -13.6%
- Top-5 (the crush wins): NFLX 2022-07-19 +7.2%, ADBE 2025-09-11 +6.5%, NFLX 2024-07-18 +5.3%, AVGO 2023-06-01 +5.0%, ADBE 2023-06-15 +4.9%

## Pre-registered gate verdict
### FAIL
- PASS: N=414 (need >= 30)
- FAIL: after-cost short-straddle mean=-0.00593 t=-3.61 (need > 0 and |t| >= 2.0)
- PASS: OOS sign stability IS=-0.00397 (n=183) OOS=-0.00749 (n=231) (need same sign, both n >= 10)
- FAIL: earnings minus non-earnings placebo (placebo mean=-0.00448) Welch t=-0.87 (need >= 2.0)

## Coverage warnings
- None
