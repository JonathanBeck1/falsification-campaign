# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **17**
- IS/OOS split: 2024-01-01
- Naive 'winners' expected from pure noise (p<0.05): **~1**

## Best in-sample variant (the one mining would 'find')
- `gap_fade_0.005_QQQ` — IS Sharpe **6.53**, OOS Sharpe 11.68
- **Deflated-Sharpe probability it's real: 100.0%** → ✅ REAL (after correction)
- Deflated Sharpe (point est.): 5.62

## Survivors — cleared deflation AND held up OOS: **3**

| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| gap_fade_0.005_QQQ | open_gap_fade | 6.53 | 11.68 |
| gap_fade_0.010_QQQ | open_gap_fade | 6.15 | 11.48 |
| gap_fade_0.015_QQQ | open_gap_fade | 5.46 | 9.92 |

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| gap_fade_0.005_QQQ | open_gap_fade | 6.53 | 11.68 |
| gap_fade_0.010_QQQ | open_gap_fade | 6.15 | 11.48 |
| gap_fade_0.015_QQQ | open_gap_fade | 5.46 | 9.92 |
| first30_mom_0.000_QQQ | first30_momentum_reversal | 0.56 | 1.09 |
| last30_mom_overnight_0.005_QQQ | last30_momentum_overnight | -0.57 | 0.92 |
| first30_mom_0.005_QQQ | first30_momentum_reversal | 0.77 | 0.79 |
| first30_mom_0.003_QQQ | first30_momentum_reversal | 1.18 | 0.76 |
| last30_mom_overnight_0.002_QQQ | last30_momentum_overnight | -1.04 | 0.04 |
| first30_rev_0.000_QQQ | first30_momentum_reversal | -0.08 | -0.02 |
| lunch_rev_-0.005_QQQ | lunchtime_reversion | -0.76 | -0.08 |
| first30_rev_0.003_QQQ | first30_momentum_reversal | -0.27 | -0.12 |
| first30_rev_0.005_QQQ | first30_momentum_reversal | -0.22 | -0.20 |
| lunch_rev_-0.008_QQQ | lunchtime_reversion | -0.51 | -0.23 |
| lunch_rev_-0.003_QQQ | lunchtime_reversion | -0.78 | -0.28 |
| last30_mom_overnight_0.000_QQQ | last30_momentum_overnight | -2.30 | -3.61 |
