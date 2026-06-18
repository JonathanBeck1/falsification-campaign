# Strategy-Mining Lab — multiple-testing-corrected

- Variants tested (N): **53**
- IS/OOS split: 2019-01-01
- Naive 'winners' expected from pure noise (p<0.05): **~3**

## Best in-sample variant (the one mining would 'find')
- `yc_proxy_z252_contra_SPY_t1` — IS Sharpe **0.85**, OOS Sharpe -0.06
- **Deflated-Sharpe probability it's real: 54.1%** → ❌ noise (fails deflation)
- Deflated Sharpe (point est.): 0.04

## Survivors — cleared deflation AND held up OOS: **0**

_None. The best 'winners' don't survive the selection correction and/or fall apart out-of-sample — exactly what noise looks like._

## Leaderboard by OUT-OF-SAMPLE Sharpe (the honest ranking)
| variant | family | IS Sharpe | OOS Sharpe |
|---|---|---|---|
| vix_below_med60_SPY | vix_regime | 0.63 | 1.18 |
| vix_below_med252_SPY | vix_regime | 0.47 | 1.08 |
| vix_z252_low_QQQ | vix_regime | 0.77 | 1.02 |
| vix_term_z252_SPY | vix_termstructure | 0.83 | 0.57 |
| gold_eq_z252_contra_SPY | gold_equity_ratio | -0.06 | 0.38 |
| bonds_eq_z60_contra_SPY_t1 | bonds_equity_ratio | 0.48 | 0.36 |
| gold_eq_z120_contra_SPY_t1 | gold_equity_ratio | -0.10 | 0.30 |
| vix_term_z252_SPY_t1 | vix_termstructure | 0.77 | 0.29 |
| bonds_eq_z252_trend_SPY | bonds_equity_ratio | -0.23 | 0.21 |
| gold_eq_z252_contra_SPY_t1 | gold_equity_ratio | 0.14 | 0.15 |
| vix_term_z60_SPY | vix_termstructure | -0.12 | 0.14 |
| bonds_eq_z120_contra_SPY | bonds_equity_ratio | 0.40 | 0.14 |
| yc_proxy_z252_trend_SPY | yield_curve_proxy | -0.49 | 0.13 |
| yc_proxy_z60_contra_SPY_t1 | yield_curve_proxy | 0.45 | 0.13 |
| bonds_eq_z120_contra_SPY_t1 | bonds_equity_ratio | 0.25 | 0.12 |
