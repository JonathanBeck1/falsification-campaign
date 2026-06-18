# T41 — Buyback-Announcement-Drift Study Result

Pre-registration: `research/buyback_drift_preregistration.md`.

## Run metadata
- Run at: 2026-06-17T15:44:32.601133+00:00
- Span: 2015-01-01 .. 2025-12-31
- Source: EDGAR full-text 8-K (Item 8.01, excl ['2.02'])
- EDGAR pagination complete (no truncation): True
- Phrases (OR): "approved a share repurchase", "approved a stock repurchase", "authorized a share repurchase", "authorized a stock repurchase", "new share repurchase program", "new stock repurchase program"
- Benchmark: SPY; abnormal return = stock - SPY (beta=1)
- PRIMARY window: car_p1_p21 = (0, 20) (t0=file+1 session)
- Round-trip cost: 15 bps/event
- IS = year < 2020, OOS = year >= 2020

## Sample accounting
- Raw qualifying accessions (Item 8.01, not 2.02): 1500
- Deduped (ticker, quarter) filings: 1479
- Distinct tickers fetched: 837
- Tickers with no price history: 95
- Complete-window events: 1303
- Events dropped (incomplete/glitch window): 11
- Matched (ticker, year) placebo windows: 4779

## Buyback-drift CAR (PRIMARY car_p1_p21 = [+1,+21])
- N events: 1303
- Gross mean abnormal return: +1.233%
- After-cost mean: +1.083%
- After-cost t-stat: +3.39
- Median: +0.667%
- Win rate: 53.3%
- Cross-event Sharpe (mean/std of CARs): +0.107
- 2x-friction-stress after-cost mean: +0.933% (t=+2.92)

## Matched (ticker, year) non-event control (placebo)
- N windows: 4779
- Mean abnormal return: -0.283%
- t-stat: -1.62

## Net of matched control (the true drift)
- Net (cohort mean - matched mean): +1.516%
- Welch t: +4.17

## IS / OOS (decay check)
- IS  (< 2020) after-cost mean: +1.248% (n=451, t=+2.87)
- OOS (>= 2020) after-cost mean: +0.995% (n=852, t=+2.31)

## Secondary windows (non-gating)
- car_p1_p63: gross +0.727% after-cost +0.577% t=+1.04 (n=1303)
- car_p1_p5: gross +1.161% after-cost +1.011% t=+5.10 (n=1303)

## Too-good tripwire / top-5 contributor inspection
- Top-5 event CARs: FLNT 2019-11-20 +63.8%, BYRN 2024-08-06 +59.3%, ETCG 2022-03-07 +55.8%, BCHG 2022-03-07 +44.1%, ENFY 2025-01-22 +42.6%
- Mean ex-top-5: +1.033% (vs full +1.233%)

## Pre-registered gate verdict
### PASS
- PASS: N=1303 (need >= 30)
- PASS: after-cost PRIMARY mean=+0.01083 t=+3.39 (need > 0 and |t| >= 2.0)
- PASS: OOS sign stability IS=+0.01248 (n=451) OOS=+0.00995 (n=852) (need same sign, both n >= 10)
- PASS: matched placebo mean=-0.00283 t=-1.62 (need |t| < 2.0)
- PASS: net vs matched control=+0.01516 t=+4.17 (need > 0 and |t| >= 2.0)

## Coverage warnings
- IBTX: price history unavailable
- IRBT: price history unavailable
- DENN: price history unavailable
- ENG: price history unavailable
- BYON: price history unavailable
- IROQ: price history unavailable
- SPI: price history unavailable
- HTBI: price history unavailable
- SEE: price history unavailable
- GLDD: price history unavailable
- BHLB: price history unavailable
- SUP: price history unavailable
- BRKL: price history unavailable
- ARC: price history unavailable
- HBI: price history unavailable
- PFIE: price history unavailable
- ODP: price history unavailable
- TSE: price history unavailable
- MOFG: price history unavailable
- VSTO: price history unavailable
- GLAE: price history unavailable
- AXL: price history unavailable
- EGIO: price history unavailable
- FFNW: price history unavailable
- TGNA: price history unavailable
- ... and 78 more
