# IPO Lock-Up Expiry Event Study — v1 Result

Pre-registration: `research/lockup_expiry_study_preregistration.md`.
This is the underlying-only (v1) test. A pass here would justify the v2
convexity (long-put) test; a fail kills the bucket cheaply.

## Run metadata
- IPO pricing window: 2019-01-01 .. 2025-06-30
- Liquidity filter: median dollar volume >= $5,000,000 over [-30,-10]
- Placebo offset: -60 trading days (reduced from pre-reg's -90 so the
  placebo baseline stays within post-IPO history; stocks trade ~124 days IPO→lock-up)
- OOS split: lock-up year <= 2022 (early) vs > 2022 (late)
- Abnormal return = stock return minus SPY return (beta=1, conservative)

## Sample accounting
- Genuine IPOs in universe: 1558 (with ticker: 1066)
- Priced + full window (real): 1046  | no price: 15  | short window: 5
- **Liquidity-filtered events (the study N): 302**
- Placebo events (liquid): 290
- OOS early (<= 2022): 240  | OOS late: 62

## Real window (around lock-up expiry)
| window | n | mean % | median % | % neg | t-stat |
|---|---|---|---|---|---|
| car_m5_m1 | 302 | -1.03 | -1.01 | 54% | -1.75 |
| car_m1_p1 | 302 | -0.02 | -0.11 | 51% | -0.03 |
| car_0_p5 | 302 | +1.17 | +0.69 | 44% | +1.53 |
| car_0_p10 | 302 | +1.35 | +0.43 | 49% | +1.48 |
| car_0_p21 | 302 | +0.93 | +0.67 | 47% | +0.82 |
| vol_ratio | 302 | 1.195 | 0.933 | — | +1.27 |

## Placebo window (60 trading days earlier)
| window | n | mean % | median % | % neg | t-stat |
|---|---|---|---|---|---|
| car_m5_m1 | 290 | -0.41 | -1.28 | 56% | -0.53 |
| car_m1_p1 | 290 | +1.12 | +0.12 | 49% | +1.59 |
| car_0_p5 | 290 | +2.54 | +0.90 | 47% | +1.81 |
| car_0_p10 | 290 | +3.04 | +0.00 | 50% | +1.66 |
| car_0_p21 | 290 | +2.06 | -2.23 | 54% | +1.10 |
| vol_ratio | 290 | 1.170 | 0.906 | — | +1.92 |

## Pre-registered gate verdict

### ❌ FAIL

- PASS: N=302 (need >= 30)
- FAIL: signal — car_0_p21 mean=+0.0093 t=+0.82 (need <0 & |t|>=2.0) OR vol_ratio mean=1.195 t=+1.27 (need >=1.25 & t>=2.0)
- PASS: beats placebo — real car_0_p21 mean=+0.0093 vs placebo mean=+0.0206 (need real more negative)
- PASS: OOS sign stable — early=+0.0007 late=+0.0424 (need same sign)

## Interpretation

A negative result here is a *correct, cheap kill* of the cleanest catalyst
in the supply thesis — and evidence the dated-supply idea is already
arbitraged. A pass advances to the v2 convexity test (single-name options).

