# PEAD Cohort-Split Event Study Result

Pre-registration: `research/pead_preregistration.md`.

## Run metadata
- Run at: 2026-06-10T00:25:41.540913+00:00
- Earnings window: 2020-01-01 .. 2025-12-31
- Fixed universe: 50 tickers
- Benchmark: SPY; abnormal return = stock return minus SPY return (beta=1)
- OOS split: event year <= 2022 vs > 2022

## Sample accounting
- Earnings dates found: 1096
- Events with complete windows: 1096
- Positive cohort: 577
- Negative cohort: 518
- Exact-zero ties dropped: 1
- Events dropped for incomplete windows: 0

## Positive cohort
| window | n | mean % | median % | t-stat |
|---|---:|---:|---:|---:|
| car_m1_p1 | 577 | +2.02 | +2.29 | +7.60 |
| car_0_p5 | 577 | +2.20 | +2.33 | +7.11 |
| car_0_p21 | 577 | +2.26 | +2.01 | +5.34 |
| car_0_p63 | 577 | +1.94 | +1.68 | +3.18 |

## Negative cohort
| window | n | mean % | median % | t-stat |
|---|---:|---:|---:|---:|
| car_m1_p1 | 518 | -1.95 | -1.74 | -7.35 |
| car_0_p5 | 518 | -2.01 | -2.27 | -6.32 |
| car_0_p21 | 518 | -1.48 | -1.43 | -3.35 |
| car_0_p63 | 518 | +0.26 | -0.67 | +0.39 |

## Primary comparison
- Positive-minus-negative mean car_0_p21: +0.0374
- Welch t-statistic: +6.11
- Early half difference: +0.0398 (t=+4.63)
- Late half difference: +0.0354 (t=+4.10)

## Pre-registered gate verdict
### PASS
- PASS: N=1095 (need >= 200)
- PASS: positive-minus-negative car_0_p21 diff=+0.0374, Welch t=+6.11 (need diff > 0 and t >= 2.0)
- PASS: OOS differences early=+0.0398, late=+0.0354 (both must be positive)

## Coverage warnings
- None
