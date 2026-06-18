# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **290**
- IS/OOS split: 2019-01-01
- Naive 'winners' expected from pure noise (p<0.05): **~14**

## Best in-sample variant (the one mining would 'find')
- `pair_SPY_IVV_W20_z1.0_h5` — IS Sharpe **4.26**, OOS Sharpe 2.54
- **Deflated-Sharpe probability it's real: 100.0%** → ✅ REAL (after correction)
- Deflated Sharpe (point est.): 3.29

## Survivors — cleared deflation AND held up OOS: **28**

| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| pair_SPY_IVV_W20_z1.0_h5 | pair_zscore | 4.26 | 2.54 |
| pair_SPY_IVV_W20_z1.0_h10 | pair_zscore | 4.06 | 2.54 |
| pair_SPY_IVV_W20_z1.0_h20 | pair_zscore | 3.97 | 2.48 |
| pair_SPY_IVV_W20_z1.5_h5 | pair_zscore | 2.87 | 1.68 |
| pair_SPY_IVV_W20_z1.5_h10 | pair_zscore | 2.69 | 1.60 |
| pair_SPY_IVV_W20_z1.5_h20 | pair_zscore | 2.57 | 1.52 |
| pair_SPY_IVV_W20_z2.0_h5 | pair_zscore | 2.15 | 1.15 |
| pair_SPY_IVV_W20_z2.0_h10 | pair_zscore | 2.12 | 1.18 |
| pair_SPY_IVV_W20_z2.0_h20 | pair_zscore | 1.90 | 1.09 |
| pair_SPY_IVV_W60_z1.0_h5 | pair_zscore | 3.43 | 2.10 |
| pair_SPY_IVV_W60_z1.0_h10 | pair_zscore | 3.05 | 2.01 |
| pair_SPY_IVV_W60_z1.0_h20 | pair_zscore | 3.03 | 1.98 |
| pair_SPY_IVV_W60_z1.5_h5 | pair_zscore | 2.70 | 1.69 |
| pair_SPY_IVV_W60_z1.5_h10 | pair_zscore | 2.49 | 1.59 |
| pair_SPY_IVV_W60_z1.5_h20 | pair_zscore | 2.27 | 1.54 |
| pair_SPY_IVV_W60_z2.0_h5 | pair_zscore | 2.02 | 1.35 |
| pair_SPY_IVV_W60_z2.0_h10 | pair_zscore | 2.04 | 1.28 |
| pair_SPY_IVV_W60_z2.0_h20 | pair_zscore | 1.80 | 1.24 |
| pair_SPY_IVV_W120_z1.0_h5 | pair_zscore | 2.79 | 1.95 |
| pair_SPY_IVV_W120_z1.0_h10 | pair_zscore | 2.58 | 1.85 |
| pair_SPY_IVV_W120_z1.0_h20 | pair_zscore | 2.57 | 1.80 |
| pair_SPY_IVV_W120_z1.5_h5 | pair_zscore | 2.39 | 1.71 |
| pair_SPY_IVV_W120_z1.5_h10 | pair_zscore | 2.27 | 1.54 |
| pair_SPY_IVV_W120_z1.5_h20 | pair_zscore | 1.98 | 1.47 |
| pair_SPY_IVV_W120_z2.0_h5 | pair_zscore | 2.01 | 1.38 |
| pair_SPY_IVV_W120_z2.0_h10 | pair_zscore | 2.00 | 1.25 |
| pair_SPY_IVV_W120_z2.0_h20 | pair_zscore | 1.77 | 1.18 |
| pair_HYG_JNK_W20_z1.0_h20 | pair_zscore | 1.53 | 0.71 |

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| pair_SPY_IVV_W20_z1.0_h5 | pair_zscore | 4.26 | 2.54 |
| pair_SPY_IVV_W20_z1.0_h10 | pair_zscore | 4.06 | 2.54 |
| pair_SPY_IVV_W20_z1.0_h20 | pair_zscore | 3.97 | 2.48 |
| pair_SPY_IVV_W60_z1.0_h5 | pair_zscore | 3.43 | 2.10 |
| pair_SPY_IVV_W60_z1.0_h10 | pair_zscore | 3.05 | 2.01 |
| pair_SPY_IVV_W60_z1.0_h20 | pair_zscore | 3.03 | 1.98 |
| pair_SPY_IVV_W120_z1.0_h5 | pair_zscore | 2.79 | 1.95 |
| pair_SPY_IVV_W120_z1.0_h10 | pair_zscore | 2.58 | 1.85 |
| pair_SPY_IVV_W120_z1.0_h20 | pair_zscore | 2.57 | 1.80 |
| pair_SPY_IVV_W120_z1.5_h5 | pair_zscore | 2.39 | 1.71 |
| pair_SPY_IVV_W60_z1.5_h5 | pair_zscore | 2.70 | 1.69 |
| pair_SPY_IVV_W20_z1.5_h5 | pair_zscore | 2.87 | 1.68 |
| pair_SPY_IVV_W20_z1.5_h10 | pair_zscore | 2.69 | 1.60 |
| pair_SPY_IVV_W60_z1.5_h10 | pair_zscore | 2.49 | 1.59 |
| pair_SPY_IVV_W60_z1.5_h20 | pair_zscore | 2.27 | 1.54 |
