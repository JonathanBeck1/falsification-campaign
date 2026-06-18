# Decision: Sell-in-May / Halloween Indicator (T49)

Pre-registration: `research/sell_in_may_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — seasonal allocation does NOT beat buy-and-hold on Sharpe; the lower drawdown is reduced market exposure (beta), not alpha.

## Numbers (after-cost, full sample, PRIMARY rf=0%)

| metric | value |
|---|---|
| sample | 1993-02-28 .. 2026-06-30 (401 months) |
| winter (Nov-Apr) mean monthly | +1.1864% (n=201) |
| summer (May-Oct) mean monthly | +0.7106% (n=200) |
| winter-summer Welch t | +1.12 |
| seasonal ann. return | +6.77% |
| buy-and-hold ann. return | +10.79% |
| seasonal ann. vol | 10.52% |
| buy-and-hold ann. vol | 14.78% |
| **seasonal Sharpe** | **+0.676** |
| **buy-and-hold Sharpe** | **+0.771** |
| Sharpe edge (seasonal - B&H) | -0.094 |
| seasonal time-in-market | 50.1% |
| seasonal Sharpe @ cash=2%/yr (sensitivity) | +0.584 |

## IS vs OOS (early half / late half)

| half | span | winter-summer diff | seasonal Sharpe | B&H Sharpe |
|---|---|---|---|---|
| IS | 1993-02-28..2009-09-30 | +0.4953% | +0.530 | +0.546 |
| OOS | 2009-10-31..2026-06-30 | +0.4436% | +0.820 | +1.007 |

## Gate result (each line PASS/FAIL)

- PASS: N — winter=201 summer=200 (need each >= 30)
- FAIL: seasonal split — winter mean=+0.01186 vs summer mean=+0.00711, Welch t=+1.12 (need winter>summer & |t|>=2.0)
- FAIL: risk-adjusted edge (DECISIVE) — seasonal Sharpe=+0.676 vs buy-and-hold Sharpe=+0.771 (need seasonal > B&H; else it's exposure not alpha)
- PASS: OOS stability — diff IS=+0.00495 OOS=+0.00444 (same sign); Sharpe-edge IS=False OOS=False (need same sign & stable verdict, all halves N>=10)

### ❌ FAIL

## Friction note

The seasonal strategy trades ~twice a year (one round trip), so total
friction is ~2 bps/yr -- immaterial to the verdict. This idea
does not live or die on costs; it lives or dies on whether holding cash
half the year buys *risk-adjusted* return or merely *less risk*.

## Artifact class (if killed)

**Decayed / exposure-driven (not alpha).** The winter>summer split can be statistically real while the seasonal *strategy* offers no Sharpe edge over buy-and-hold: it simply holds ~half the market exposure, so it shows lower vol and lower drawdown without higher reward-per-unit-risk. That is risk reduction, not edge -- the same dollar of risk-budget in B&H sized down would match it. (brain/30: real-mechanism-but-no-survivable-edge.)

## Honest verdict

Winter monthly returns (+1.186%) are higher than summer (+0.711%) directionally, but the gap is in-noise (Welch t=+1.12). The seasonal strategy's Sharpe (+0.676) does NOT beat buy-and-hold's (+0.771). The strategy's only genuine benefit is lower volatility/drawdown from being in cash half the year -- that is reduced exposure, not alpha. A kill here does NOT prove winter == summer in raw mean; it proves the publicized 'edge' offers no risk-adjusted advantage net of its lower market participation.

## Files

- `src/trader/catalysts/sell_in_may.py` -- pure core + gate
- `tests/financial/test_sell_in_may.py` -- network-free tests
- `scripts/run_sell_in_may_study.py` -- end-to-end runner
- `data/sell_in_may_results.txt` -- raw run output

## Registry status update line (paste into brain/34)

`- ❌ **T49** Sell-in-May / Halloween — *KILL: winter>summer directionally but in-noise (t=+1.12); seasonal Sharpe 0.68 < B&H 0.77 — exposure reduction, not alpha.*`

