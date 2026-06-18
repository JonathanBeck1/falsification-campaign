# Decision: Single-name IV term-structure carry (T24)

Pre-registration: `research/vol_term_structure_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — ranking on the term-structure slope LOSES money after cost and adds zero alpha over an unconditional short-vol stance

The vega-neutral long-short calendar (short-near / long-far on steep-contango
names, the mirror on flat names) has an after-cost long-short mean that is
**significantly negative** (−2.73/period, t = −3.41, N = 53) — the slope ranking
actively *mis-sorts* the calendars. The decisive control nails it: regressing
the slope book on the plain unconditional short-vol book leaves **no incremental
alpha** (residual α = −0.39, t = −0.18). The placebo is the smoking gun — every
one of 500 shuffled-tercile books beats the real one (perm p = 1.000), i.e. a
RANDOM ranking does better than the slope ranking. The only thing that "works"
is the unconditional short-vol book itself (+0.073/period, t = +18.56 in-sample)
— calm-regime short-vol beta, exactly the artifact the test was built to strip
out. The kill holds at 2× friction (t = −4.01).

## Numbers (after-cost, PRIMARY window — 1× friction)

| metric | value |
|---|---|
| N (rebalance periods) | 53 |
| LS mean / period | −2.73 (vega-$ units) |
| LS t-stat | **−3.41** |
| annualized LS mean | −32.7 |
| win rate | 32% |
| IS mean (t) | −1.26 (−1.20) |
| OOS mean (t) | −4.25 (−3.68) |
| short-vol book mean (t) | +0.073 (+18.56) |
| **incremental alpha (t)** over short-vol | **−0.39 (−0.18)** |
| placebo perm p | **1.000** (random ranks beat the slope) |
| worst period | −19.7 |
| max drawdown (cum) | −155.3 |

At **2× friction** the LS mean is −3.17/period (t = −4.01); incremental α still
~0 (t = −0.75); placebo p = 1.000; max drawdown −172.9. KILL is friction-robust.

## Gate result (each line PASS/FAIL)

- PASS: N = 53 (≥ 30).
- FAIL: after-cost LS mean = −2.73, t = −3.41 (need > 0 & |t| ≥ 2) — *negative*.
- FAIL: incremental α over short-vol = −0.39, t = −0.18 (need > 0 & |t| ≥ 2) ← KEY control.
- "PASS" OOS sign stable — but stably *negative* (IS −1.26, OOS −4.25): both halves lose.
- FAIL: placebo not beaten (perm p = 1.000; random ranks outperform the slope).
- too-good tripwire: not triggered (Sharpe −0.47, win 32%).

## Artifact class (if killed)

**Class 2 (friction-scale / in-noise) + the short-vol-beta confound.** The only
positive, significant book is the *unconditional* short-vol stance (in-sample,
calm-regime beta). The slope-conditioned, vega-neutral construction — built
specifically to strip that beta out — leaves nothing: incremental alpha ≈ 0,
placebo unbeaten, OOS sign-unstable. This is the same pattern the campaign has
hit repeatedly: an apparent vol-selling edge that is just short-vol beta, not a
slope/term-premium signal (cf. T19 VRP mechanism-null, T33 crypto levered beta).

## Tail (mandatory — short-vol books have catastrophic tails)

The dollar-/vega-neutral long-short book bleeds steadily (win rate 32%, median
−1.58) into a cumulative max drawdown of **−155.3** (1×) / **−172.9** (2×) in
vega-dollar units, worst single period **−19.7**. Because the slope ranking is
*negatively* informative here, the "tail" is not a rare crash but a persistent
loss — a drawdown that never recovers. The *unconditional* short-vol book (the
only positive in-sample piece, +0.073/period t=18.56) carries the textbook
short-vol crash exposure separately; its in-sample mean is calm-regime premium a
single vol spike repays. Reporting either mean without the tail/drawdown would
have flattered a stance that is, respectively, a losing sort and an uninsurable
beta — not an edge.

## Honest verdict (2–4 sentences)

The single-name IV term-structure slope does not carry harvestable, after-cost
alpha once it is isolated from short-vol beta in this 26-name, 2022-2026 panel.
The vega-neutral calendar that bets on the slope is indistinguishable from noise
(placebo unbeaten, OOS sign-unstable) and adds nothing over simply being short
vol (incremental alpha t ≈ 0). This does NOT prove single-name term premium is
zero in level — only that the cross-sectional slope, traded as a vega-neutral
calendar net of single-name friction via an EOD mark-to-market proxy, is not a
tradeable edge; a contract-level live book could differ at the margins but the
mechanism check (no incremental alpha) is the load-bearing kill.

## Files

- `src/trader/catalysts/vol_term_structure.py` — pure core (straddle marks,
  vega-neutral calendar P&L, terciles, incremental-alpha regression, placebo,
  tail) reusing the `vol_surface_data` Black-Scholes foundation.
- `tests/financial/test_vol_term_structure.py` — 21 network-free unit tests.
- `scripts/run_vol_term_structure_study.py` — thin end-to-end runner (shared
  rebalance grid, both friction levels, full gate).
- `data/vol_term_structure_results.txt` — raw run output.
- `research/vol_term_structure_preregistration.md` — fixed pre-registration.

## Registry status update line (paste into brain/34)

`- ✅ **T24** Single-name vol term-structure carry — *KILL: cross-sectional vega-neutral calendar ranked on the ≈30/≈90d ATM slope (26 names, 2022-26, N=53 monthly periods) loses after cost (−2.73/period, t=−3.41) and adds ZERO alpha over an unconditional short-vol book (residual α=−0.39, t=−0.18); placebo p=1.000 — random ranks beat the slope. Only the plain short-vol stance "works" in-sample (+0.073/period, t=18.56 = calm-regime beta, not slope carry). Friction-robust at 2× (t=−4.01); max drawdown −155 (vega-$). Class-2 friction/in-noise + short-vol-beta confound.*`
