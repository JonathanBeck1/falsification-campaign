# T43 — Earnings-Announcement Premium Study Result

Pre-registration: `research/earnings_premium_preregistration.md`.

## Run metadata
- Run at: 2026-06-14T13:51:13.081589+00:00
- Span: 2015-01-01 .. 2025-12-31
- Universe: 49 tickers (49 contributed events)
- Benchmark: SPY; abnormal return = stock - SPY (beta=1)
- PRIMARY window: car_m1_p1 = (-1, 1) (event-day)
- Round-trip cost: 10 bps/event
- IS = year <= 2020, OOS = year > 2020

## Sample accounting
- Raw earnings dates in span: 2156
- Complete-window events: 2156
- Events dropped (incomplete/glitch window): 0
- Placebo (non-earnings) windows: 2940

## Announcement-window premium (PRIMARY car_m1_p1)
- N events: 2156
- Gross mean abnormal return: +0.344%
- After-cost mean: +0.244%
- After-cost t-stat: +1.85
- Median: +0.182%
- Win rate: 51.8%
- Event-window Sharpe (mean/std of CARs): +0.056

## Same-stock non-earnings baseline (placebo)
- N windows: 2940
- Mean abnormal return: +0.041%
- t-stat: -1.27

## Premium net of baseline (the true announcement premium)
- Premium (event mean - non-earnings mean): +0.303%
- Welch t: +2.17

## IS / OOS (decay check)
- IS  (<= 2020) after-cost mean: +0.459% (n=1176, t=+2.76)
- OOS (>  2020) after-cost mean: -0.014% (n=980, t=-0.07)

## Jump-risk vs alpha
- Corr(|window CAR|, window vol): +0.734
  (high positive => premium tracks jump-risk magnitude = compensated variance, not alpha)

## Secondary windows (non-gating)
- car_0_p1: gross +0.254% after-cost +0.154% t=+1.18 (n=2156)
- car_0_p0: gross +0.207% after-cost +0.107% t=+0.91 (n=2156)

## Too-good tripwire / top-5 contributor inspection
- Top-5 event CARs: AMD 2016-04-22 +36.5%, AVGO 2024-12-13 +34.4%, ORCL 2025-09-10 +29.6%, CRM 2020-08-26 +29.6%, TSLA 2019-10-24 +25.9%
- Mean ex-top-5: +0.272% (vs full +0.344%)

## Pre-registered gate verdict
### FAIL
- PASS: N=2156 (need >= 30)
- FAIL: after-cost announcement mean=+0.00244 t=+1.85 (need > 0 and |t| >= 2.0)
- FAIL: OOS sign stability IS=+0.00459 (n=1176) OOS=-0.00014 (n=980) (need same sign, both n >= 10)
- PASS: placebo non-earnings mean=+0.00041 t=-1.27 (need |t| < 2.0)
- PASS: premium vs same-stock baseline=+0.00303 (need > 0)

## Coverage warnings
- None
