# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **174**
- IS/OOS split: 2010-01-01
- Naive 'winners' expected from pure noise (p<0.05): **~9**

## Best in-sample variant (the one mining would 'find')
- `meanrev_10_1.5_DIA` — IS Sharpe **0.97**, OOS Sharpe 0.29
- **Deflated-Sharpe probability it's real: 75.3%** → ❌ noise (fails deflation)
- Deflated Sharpe (point est.): 0.18

## Survivors — cleared deflation AND held up OOS: **0**

_None. The best 'winners' don't survive the selection correction and/or fall apart out-of-sample — exactly what noise looks like._

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| tsmom_20_lo_SPY | tsmom | 0.35 | 0.90 |
| macross_10_100_lo_SPY | ma_cross | 0.66 | 0.84 |
| macross_5_200_lo_SPY | ma_cross | 0.66 | 0.82 |
| tsmom_10_lo_SPY | tsmom | -0.08 | 0.82 |
| macross_10_200_lo_SPY | ma_cross | 0.79 | 0.82 |
| macross_5_20_lo_SPY | ma_cross | 0.16 | 0.82 |
| tsmom_10_lo_DIA | tsmom | 0.10 | 0.80 |
| macross_5_100_lo_SPY | ma_cross | 0.59 | 0.79 |
| tsmom_100_lo_SPY | tsmom | 0.58 | 0.76 |
| tsmom_50_lo_SPY | tsmom | 0.39 | 0.76 |
| tsmom_150_lo_SPY | tsmom | 0.73 | 0.72 |
| macross_20_200_lo_SPY | ma_cross | 0.75 | 0.72 |
| macross_10_50_lo_SPY | ma_cross | 0.52 | 0.71 |
| dow_0_SPY | seasonal_dow | 0.34 | 0.68 |
| macross_20_100_lo_SPY | ma_cross | 0.51 | 0.68 |
