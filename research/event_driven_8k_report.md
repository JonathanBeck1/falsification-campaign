# SEC 8-K Item-Type Event Study Result

Pre-registration: `research/event_driven_8k_preregistration.md`.

## Run metadata
- Run at: 2026-06-10T00:40:36.402258+00:00
- Filing window: 2020-01-01 .. 2024-12-31
- Fixed universe: 30 symbols (BRK-B pre-registered skip)
- Benchmark: SPY; abnormal return = stock return minus SPY return (beta=1)
- OOS split: filing year <= 2022 vs > 2022

## Sample accounting
- Filings inspected: 1868
- Filings with a target item: 1315
- Filings with usable CARs: 1315

## Item cohorts
| item | n | mean [0,+5] % | median [0,+5] % | t | mean [0,+21] % | median [0,+21] % | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1.01 | 79 | -0.41 | +0.03 | -0.57 | +0.45 | -0.03 | +0.38 |
| 2.02 | 608 | +0.50 | +0.58 | +1.55 | +0.87 | +0.64 | +1.97 |
| 5.02 | 401 | +0.16 | +0.15 | +0.68 | +0.33 | +0.48 | +0.79 |
| 7.01 | 353 | +0.27 | +0.23 | +0.89 | +0.66 | -0.21 | +1.23 |

## Primary comparison
- Item 2.02 minus Item 7.01 mean car_0_p21: +0.0021
- Welch t-statistic: +0.31
- Early-half difference: -0.0098
- Late-half difference: +0.0233

## Pre-registered gate verdict
### FAIL
- FAIL: Item 2.02 minus 7.01 car_0_p21 diff=+0.0021, Welch t=+0.31 (need |t| >= 2.0)
- FAIL: Item 1.01 mean=+0.0045, t=+0.38 (need mean > 0 and t >= 2.0)
- PASS: Item 5.02 t=+0.79 (need |t| < 2.0)

## Coverage warnings
- BRK-B: skipped per pre-registration
