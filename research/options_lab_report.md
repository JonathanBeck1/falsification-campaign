# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **48**
- IS/OOS split: 2023-06-01
- Naive 'winners' expected from pure noise (p<0.05): **~2**

## Best in-sample variant (the one mining would 'find')
- `opt_put_skew_reg10_lowlong` — IS Sharpe **1.03**, OOS Sharpe 0.02
- **Deflated-Sharpe probability it's real: 35.7%** → ❌ noise (fails deflation)
- Deflated Sharpe (point est.): -0.20

## Survivors — cleared deflation AND held up OOS: **0**

_None. The best 'winners' don't survive the selection correction and/or fall apart out-of-sample — exactly what noise looks like._

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| opt_term_slope_z10_trend | opt_term_slope | 0.16 | 0.93 |
| opt_atm_vol_reg10_lowlong | opt_atm_vol | 0.36 | 0.80 |
| opt_atm_vol_z10_contra | opt_atm_vol | 0.63 | 0.64 |
| opt_put_skew_z20_contra | opt_put_skew | 0.51 | 0.59 |
| opt_atm_vol_z50_contra | opt_atm_vol | 0.38 | 0.55 |
| opt_atm_vol_z100_contra | opt_atm_vol | 0.18 | 0.53 |
| opt_atm_vol_reg50_lowlong | opt_atm_vol | 0.29 | 0.50 |
| opt_term_slope_reg20_highlong | opt_term_slope | 0.42 | 0.40 |
| opt_term_slope_reg50_lowlong | opt_term_slope | -0.37 | 0.34 |
| opt_put_skew_reg50_lowlong | opt_put_skew | 0.36 | 0.30 |
| opt_term_slope_reg10_highlong | opt_term_slope | 0.17 | 0.21 |
| opt_atm_vol_z20_contra | opt_atm_vol | 0.18 | 0.19 |
| opt_put_skew_z50_contra | opt_put_skew | 0.44 | 0.17 |
| opt_put_skew_z100_trend | opt_put_skew | -0.56 | 0.14 |
| opt_term_slope_z50_contra | opt_term_slope | -0.44 | 0.13 |
