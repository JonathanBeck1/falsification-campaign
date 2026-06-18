# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **1044**
- IS/OOS split: 2019-01-01
- Naive 'winners' expected from pure noise (p<0.05): **~52**

## Best in-sample variant (the one mining would 'find')
- `tsmom_20_lo_KWEB` — IS Sharpe **0.90**, OOS Sharpe 0.28
- **Deflated-Sharpe probability it's real: 12.3%** → ❌ noise (fails deflation)
- Deflated Sharpe (point est.): -0.51

## Survivors — cleared deflation AND held up OOS: **0**

_None. The best 'winners' don't survive the selection correction and/or fall apart out-of-sample — exactly what noise looks like._

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| tsmom_10_lo_MLPX | tsmom | -0.06 | 1.19 |
| tsmom_5_lo_GREK | tsmom | -0.23 | 1.18 |
| tsmom_5_lo_AMLP | tsmom | 0.46 | 1.15 |
| tsmom_10_lo_AMLP | tsmom | -0.02 | 1.11 |
| dow_1_GREK | seasonal_dow | 0.11 | 1.11 |
| dow_0_MLPX | seasonal_dow | 0.14 | 1.00 |
| tsmom_10_lo_GREK | tsmom | 0.18 | 1.00 |
| macross_10_20_lo_GREK | ma_cross | 0.31 | 1.00 |
| dow_0_AMLP | seasonal_dow | -0.15 | 1.00 |
| volbreak_20_AMLP | vol_breakout | 0.03 | 1.00 |
| tsmom_20_lo_BIZD | tsmom | 0.05 | 0.99 |
| dow_1_DGS | seasonal_dow | 0.41 | 0.98 |
| volbreak_50_MLPX | vol_breakout | -0.23 | 0.97 |
| tsmom_5_lo_DGS | tsmom | 0.01 | 0.96 |
| macross_5_20_lo_MLPX | ma_cross | 0.14 | 0.95 |

## Universe coverage

### Kept

- IJR: 4131 days
- VBR: 4131 days
- IJS: 4131 days
- IWN: 4131 days
- IWO: 4131 days
- SLY: 3382 days
- SLYG: 4131 days
- RWR: 4131 days
- KBWY: 3900 days
- SCHH: 3871 days
- AMLP: 3969 days
- MLPX: 3227 days
- BIZD: 3349 days
- VWO: 4131 days
- SCZ: 4131 days
- DGS: 4131 days
- GREK: 3643 days
- KWEB: 3231 days

### Dropped

