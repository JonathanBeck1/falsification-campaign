# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **870**
- IS/OOS split: 2019-01-01
- Naive 'winners' expected from pure noise (p<0.05): **~44**

## Best in-sample variant (the one mining would 'find')
- `volbreak_200_DIA` — IS Sharpe **1.12**, OOS Sharpe -0.18
- **Deflated-Sharpe probability it's real: 55.2%** → ❌ noise (fails deflation)
- Deflated Sharpe (point est.): 0.05

## Survivors — cleared deflation AND held up OOS: **0**

_None. The best 'winners' don't survive the selection correction and/or fall apart out-of-sample — exactly what noise looks like._

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| macross_5_20_lo_SPY | ma_cross | 0.33 | 1.34 |
| tsmom_20_lo_QQQ | tsmom | 1.01 | 1.29 |
| tsmom_10_lo_SPY | tsmom | 0.36 | 1.25 |
| tsmom_20_lo_SPY | tsmom | 0.63 | 1.20 |
| macross_5_20_lo_QQQ | ma_cross | 0.64 | 1.15 |
| macross_5_200_lo_QQQ | ma_cross | 0.67 | 1.13 |
| tsmom_10_lo_QQQ | tsmom | 0.23 | 1.12 |
| tsmom_10_lo_XLK | tsmom | 0.43 | 1.12 |
| tsmom_20_lo_XLK | tsmom | 0.70 | 1.11 |
| macross_5_20_lo_XLK | ma_cross | 0.43 | 1.09 |
| macross_10_100_lo_SPY | ma_cross | 0.73 | 1.07 |
| macross_10_20_lo_XLK | ma_cross | 0.51 | 1.06 |
| tsmom_200_lo_XLK | tsmom | 0.56 | 1.06 |
| macross_5_50_lo_QQQ | ma_cross | 0.59 | 1.05 |
| macross_20_100_lo_GLD | ma_cross | 0.00 | 1.05 |
