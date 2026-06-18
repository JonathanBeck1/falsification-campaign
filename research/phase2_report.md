# Phase 2 — Catalyst-Drift Analysis

- Catalog (deduped): **1512 unique events**
- Events with computable drift: **1512**
- Window: market-adjusted CAR[+1,+21] vs SPY (beta=1)
- t0 = move date, measurement window EXCLUDES t0 (no look-ahead)
- Gate: N>=30 AND |t|>=2 AND OOS sign stable (2020-22 vs 2023-26)

## Verdict: **5 cohort(s) survive** out of 27 tested

_Note: at naive p<0.05, you'd expect ~1.4 winners from pure noise across 27 cohorts. Be skeptical of single-cohort passes._

### 🟡 Cohorts that passed the gate

**market_wide_selloff__down** (N=252):
- PASS: N=252 (need >= 30)
- PASS: CAR[+1,+21] mean=+3.16% t=+4.76 (need |t|>=2.0)
- PASS: OOS sign stable — early=+3.10% (N=199) late=+3.39% (N=53)
- median +21d CAR: +1.99%, % positive: 59%

**product_news__up** (N=48):
- PASS: N=48 (need >= 30)
- PASS: CAR[+1,+21] mean=+8.15% t=+3.78 (need |t|>=2.0)
- PASS: OOS sign stable — early=+10.36% (N=30) late=+4.48% (N=18)
- median +21d CAR: +4.14%, % positive: 69%

**rotation_flow__up** (N=123):
- PASS: N=123 (need >= 30)
- PASS: CAR[+1,+21] mean=+3.71% t=+3.63 (need |t|>=2.0)
- PASS: OOS sign stable — early=+2.01% (N=79) late=+6.77% (N=44)
- median +21d CAR: +2.29%, % positive: 63%

**idiosyncratic_unknown__down** (N=148):
- PASS: N=148 (need >= 30)
- PASS: CAR[+1,+21] mean=+3.32% t=+3.37 (need |t|>=2.0)
- PASS: OOS sign stable — early=+3.03% (N=71) late=+3.58% (N=77)
- median +21d CAR: +2.48%, % positive: 60%

**idiosyncratic_unknown__up** (N=232):
- PASS: N=232 (need >= 30)
- PASS: CAR[+1,+21] mean=+2.83% t=+2.82 (need |t|>=2.0)
- PASS: OOS sign stable — early=+4.12% (N=97) late=+1.90% (N=135)
- median +21d CAR: +1.10%, % positive: 55%

## Full leaderboard (all cohorts, by |t-stat|)

| cohort | N | CAR+21 mean % | t | % pos | early N | early CAR % | late N | late CAR % | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| market_wide_selloff__down | 252 | +3.16 | +4.76 | 59% | 199 | +3.10 | 53 | +3.39 | ✅ |
| product_news__up | 48 | +8.15 | +3.78 | 69% | 30 | +10.36 | 18 | +4.48 | ✅ |
| rotation_flow__up | 123 | +3.71 | +3.63 | 63% | 79 | +2.01 | 44 | +6.77 | ✅ |
| idiosyncratic_unknown__down | 148 | +3.32 | +3.37 | 60% | 71 | +3.03 | 77 | +3.58 | ✅ |
| idiosyncratic_unknown__up | 232 | +2.83 | +2.82 | 55% | 97 | +4.12 | 135 | +1.90 | ✅ |
| regulatory_action__down | 10 | +9.28 | +3.76 | 90% | 5 | +6.14 | 5 | +12.43 | ❌ |
| geopolitical__up | 29 | +6.13 | +3.03 | 72% | 10 | +6.38 | 19 | +5.99 | ❌ |
| other__up | 21 | +6.04 | +2.68 | 76% | 13 | +6.60 | 8 | +5.12 | ❌ |
| product_news__down | 7 | +11.27 | +2.03 | 100% | 5 | +14.78 | 2 | +2.49 | ❌ |
| exec_change__up | 15 | -5.10 | -1.87 | 20% | 7 | -6.73 | 8 | -3.67 | ❌ |
| rotation_flow__down | 26 | +4.39 | +1.81 | 62% | 11 | +3.42 | 15 | +5.10 | ❌ |
| market_wide_selloff__up | 97 | +1.74 | +1.67 | 61% | 96 | +1.82 | 1 | -5.38 | ❌ |
| macro_data__down | 23 | -3.36 | -1.60 | 22% | 20 | -4.68 | 3 | +5.45 | ❌ |
| macro_fed__down | 79 | -2.00 | -1.57 | 48% | 59 | -3.81 | 20 | +3.36 | ❌ |
| earnings_results__up | 134 | +1.26 | +1.31 | 51% | 66 | -0.34 | 68 | +2.80 | ❌ |
| other__down | 4 | +4.48 | +1.12 | 50% | 1 | +16.02 | 3 | +0.64 | ❌ |
| geopolitical__down | 24 | +2.19 | +0.94 | 50% | 14 | +7.53 | 10 | -5.29 | ❌ |
| guidance_update__down | 4 | +2.51 | +0.70 | 50% | 2 | +7.54 | 2 | -2.53 | ❌ |
| macro_data__up | 31 | +1.48 | +0.68 | 42% | 24 | -0.76 | 7 | +9.15 | ❌ |
| earnings_results__down | 105 | +0.55 | +0.48 | 55% | 47 | -1.24 | 58 | +2.01 | ❌ |
| merger_acquisition__up | 6 | +2.16 | +0.37 | 33% | 6 | +2.16 | 0 | +nan | ❌ |
| exec_change__down | 9 | -1.12 | -0.37 | 56% | 7 | -3.04 | 2 | +5.61 | ❌ |
| macro_fed__up | 61 | -0.36 | -0.27 | 49% | 44 | -2.02 | 17 | +3.96 | ❌ |
| analyst_action__up | 1 | -5.99 | +0.00 | 0% | 1 | -5.99 | 0 | +nan | ❌ |
| analyst_action__down | 1 | +4.16 | +0.00 | 100% | 0 | +nan | 1 | +4.16 | ❌ |
| guidance_update__up | 1 | -6.90 | +0.00 | 0% | 1 | -6.90 | 0 | +nan | ❌ |
| regulatory_action__up | 1 | +2.39 | +0.00 | 100% | 0 | +nan | 1 | +2.39 | ❌ |
