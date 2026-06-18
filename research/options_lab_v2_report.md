# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **56**
- IS/OOS split: 2023-06-01
- Naive 'winners' expected from pure noise (p<0.05): **~3**

## Best in-sample variant (the one mining would 'find')
- `optv2_gex_depth_proxy_z50_trend` — IS Sharpe **1.42**, OOS Sharpe -0.52
- **Deflated-Sharpe probability it's real: 62.1%** → ❌ noise (fails deflation)
- Deflated Sharpe (point est.): 0.17

## Survivors — cleared deflation AND held up OOS: **0**

_None. The best 'winners' don't survive the selection correction and/or fall apart out-of-sample — exactly what noise looks like._

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| optv2_term_curvature_reg20_highlong | optv2_term_curvature | 0.63 | 1.39 |
| optv2_term_curvature_reg50_highlong | optv2_term_curvature | 0.63 | 1.39 |
| optv2_depth_imbalance_z20_trend | optv2_depth_imbalance | 0.40 | 0.99 |
| optv2_depth_imbalance_reg20_highlong | optv2_depth_imbalance | 0.98 | 0.98 |
| optv2_depth_imbalance_z50_trend | optv2_depth_imbalance | 0.48 | 0.93 |
| optv2_avg_spread_pct_z50_contra | optv2_avg_spread_pct | 0.39 | 0.82 |
| optv2_avg_spread_pct_z20_contra | optv2_avg_spread_pct | 0.59 | 0.71 |
| optv2_pc_size_ratio_z20_contra | optv2_pc_size_ratio | -0.58 | 0.68 |
| optv2_skew_25d_reg20_lowlong | optv2_skew_25d | 0.34 | 0.68 |
| optv2_gex_depth_proxy_reg20_lowlong | optv2_gex_depth_proxy | -0.97 | 0.68 |
| optv2_gex_depth_proxy_z20_contra | optv2_gex_depth_proxy | -0.88 | 0.66 |
| optv2_depth_imbalance_reg50_highlong | optv2_depth_imbalance | 0.66 | 0.61 |
| optv2_pc_size_ratio_reg20_lowlong | optv2_pc_size_ratio | -0.59 | 0.55 |
| optv2_skew_25d_z20_contra | optv2_skew_25d | 0.28 | 0.55 |
| optv2_gex_depth_proxy_z50_contra | optv2_gex_depth_proxy | -1.42 | 0.52 |
