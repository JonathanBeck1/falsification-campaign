# Following Saba's 13D into CEFs — Event Study Result

Pre-registration: `research/cef_activist_study_preregistration.md`.
NAV-free: excess return = target CEF total return minus PCEF (broad-CEF ETF).
Follower entry = the trading day AFTER the 13D is public (t0+1).

## Run metadata
- Saba initial SC 13D window: 2022-01-01 .. 2025-06-30
- Benchmark: PCEF (broad closed-end-fund ETF)
- OOS split: campaign year <= 2023 (early) vs > 2023 (late)

## Sample accounting
- Saba CEF campaigns (initial 13D): 82
- With >=6mo price history (study N): 62  | no price: 20  | short window: 0
- OOS early: 39  | OOS late: 23

## Excess return vs PCEF, by window
| window | n | mean % | median % | % pos | t-stat |
|---|---|---|---|---|---|
| pre-runup [-126,-1] (NOT capturable) | 62 | -0.98 | -1.01 | 47% | -1.14 |
| announcement [-1,+1] | 62 | +0.23 | +0.26 | 65% | +1.78 |
| capturable +1m | 62 | +1.44 | +0.84 | 65% | +2.78 |
| capturable +3m | 62 | +0.96 | +0.83 | 58% | +1.49 |
| capturable +6m (PRIMARY) | 62 | +2.02 | -0.09 | 50% | +1.81 |
| capturable +12m | 62 | +3.02 | -0.18 | 48% | +1.90 |

## Pre-registered gate verdict

### ❌ FAIL

- PASS: N=62 (need >= 30)
- FAIL: capturable exc_6m mean=+0.0202 t=+1.81 (need >0 & t>=2.0)
- PASS: drift exceeds pre-run-up — exc_6m mean=+0.0202 vs exc_pre mean=-0.0098
- PASS: OOS sign stable — early=+0.0242 late=+0.0136

## How to read this

The decomposition is the point: if the excess return sits in **pre-runup**
and **announcement** but the **capturable +6m** drift (entering the day after
the public filing) is flat, the activist edge is real but **priced by
disclosure** — you'd have to BE the activist, not follow one. A positive,
significant capturable +6m that exceeds the pre-runup is the rare good case.

