# T26 — Put-Call Parity / Implied Borrow Study Result

Pre-registration: `research/putcall_parity_borrow_preregistration.md`.

## Run metadata
- Run at: 2026-06-17T16:59:51.581919+00:00
- Span: 2022-01-01 .. 2026-06-13
- Universe: 24 single names (AAPL/AMZN/NVDA excluded: collecting)
- Benchmark: SPY; abnormal fwd return = stock_fwd - SPY_fwd (beta=1)
- PRIMARY window: fwd_21d (21 td)
- Rebalance: monthly (first trade-date each month)
- Round-trip cost: 20 bps/rebalance (long-short, 2 legs)
- IS = year <= 2023, OOS = year > 2023

## Implied-borrow level & dispersion (the DATA_WALL evidence)
Per-name median implied carry q* (annualized; ~borrow for these zero/low-div names):
  - ADBE:    -48.2 bps/yr (n_days=1115)
  - AMAT:    +20.0 bps/yr (n_days=1115)
  - AMD:    -50.0 bps/yr (n_days=1115)
  - AVGO:    +23.9 bps/yr (n_days=1115)
  - BKNG:    -19.6 bps/yr (n_days=1115)
  - COST:     +8.9 bps/yr (n_days=1115)
  - CSCO:    +87.4 bps/yr (n_days=1115)
  - GOOG:    -12.8 bps/yr (n_days=1115)
  - GOOGL:    -22.1 bps/yr (n_days=1115)
  - HON:    +84.7 bps/yr (n_days=1114)
  - INTU:    +13.6 bps/yr (n_days=1115)
  - ISRG:    -48.1 bps/yr (n_days=1115)
  - LIN:    +67.6 bps/yr (n_days=1079)
  - LRCX:    +31.8 bps/yr (n_days=1079)
  - META:    -31.7 bps/yr (n_days=1025)
  - MU:    -19.7 bps/yr (n_days=1115)
  - NFLX:    -38.2 bps/yr (n_days=1115)
  - PEP:   +109.4 bps/yr (n_days=1115)
  - QCOM:    +51.4 bps/yr (n_days=1115)
  - REGN:    -33.4 bps/yr (n_days=1115)
  - TMUS:    +30.7 bps/yr (n_days=1115)
  - TSLA:    -45.0 bps/yr (n_days=1115)
  - TXN:   +100.0 bps/yr (n_days=1115)
  - VRTX:    -33.2 bps/yr (n_days=1115)
- Cross-name pooled median q*: -1.9 bps/yr
- Cross-name IQR of median q* (the dispersion to sort on): +69.9 bps/yr
- Median per-date top-minus-bottom-tercile borrow dispersion: +228.8 bps/yr

## Cross-sectional spread (PRIMARY fwd_21d, low-borrow minus high-borrow)
- N rebalances: 53
- Gross mean spread: +0.7653%
- After-cost mean spread: +0.5653%
- After-cost t-stat: +0.64
- Median spread: -0.2231%
- Win rate (spread > 0): 47.2%
- Spread Sharpe (mean/std): +0.119

## IS / OOS (decay check)
- IS  (<= 2023) after-cost: -0.2397% (n=24, t=-0.20)
- OOS (>  2023) after-cost: +1.2314% (n=29, t=+0.98)

## Placebo (shuffled-borrow sort)
- N: 53
- Mean spread: -0.7398%
- t-stat: -1.68

## Secondary windows (non-gating)
- fwd_5d: gross +0.1528% after-cost -0.0472% t=-0.11 (n=54)
- fwd_63d: gross +1.8138% after-cost +1.6138% t=+1.28 (n=51)

## Top-5 |spread| rebalances (contributor inspection)
- 2026-04-01: spread +23.78% (low +17.84% / high -5.94%, disp +151bps, n=24)
- 2023-01-03: spread +20.10% (low +17.31% / high -2.79%, disp +183bps, n=24)
- 2023-05-01: spread +13.33% (low +12.36% / high -0.97%, disp +278bps, n=24)
- 2024-12-02: spread -11.84% (low -4.21% / high +7.63%, disp +259bps, n=24)
- 2025-10-01: spread +11.28% (low +10.12% / high -1.16%, disp +166bps, n=24)

## Pre-registered gate verdict
### FAIL
- PASS: cross-sectional borrow dispersion=+228.8 bps/yr (need >= 100 bps to have anything to sort on)
- PASS: N=53 (need >= 30)
- FAIL: after-cost low-minus-high spread=+0.5653% t=+0.64 (need > 0 and |t| >= 2.0)
- FAIL: OOS sign stability IS=-0.2397% (n=24) OOS=+1.2314% (n=29) (need same sign, both n >= 10)
- PASS: placebo (shuffled-borrow) t=-1.68 (need |t| < 2.0)
