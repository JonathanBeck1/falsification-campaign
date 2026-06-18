# Decision: Phase 2 — 4 of 5 "survivors" killed by mega-cap-beta baseline check

> **SUPERSEDED (same day):** `product_news__up` was subsequently KILLED by the
> matched (ticker, year) control test — net drift +0.14%, t=+0.07, perm p=0.47.
> See `2026-06-10-product-news-matched-control-kill.md`. No watchlist remains.

Date: 2026-06-10
Status: catalog-drift Phase 2 done. One marginal candidate survives both the gate
and the baseline correction; documented for further inspection, NOT deployed.

## What we ran

For each (catalyst_category, direction) cohort in the 1,512-event clean catalog,
computed market-adjusted CAR[+1,+21] vs SPY (beta=1). Window EXCLUDES t0 (no
look-ahead — lesson from the prior PEAD kill). Pre-registered gate: N≥30,
|t|≥2, OOS sign stable (2020–22 vs 2023–26).

**27 cohorts tested. 5 passed the raw gate.**

## What the raw gate missed (caught by baseline check)

**Baseline drift across all 1,492 events with computable drift: +2.39%.**

This is the systematic outperformance of mega-cap tech vs SPY during 2020–2026
(NVDA 10x, MSFT 2x, AVGO 5x, etc.). It is NOT a catalyst effect — it's a regime
effect that contaminates every cohort the catalog is built from.

The smoking gun: in 11 of 13 categories with both directions, "_up" cohorts AND
"_down" cohorts show drift of THE SAME SIGN. If "after a big up day" and "after
a big down day" both produce positive +21d drift, the drift isn't caused by the
event — it's mega-cap baseline.

## Survivor verdict after baseline correction

| cohort | raw CAR % | baseline | net % | verdict |
|---|---:|---:|---:|---|
| market_wide_selloff__down | +3.16 | +2.39 | **+0.77** | 🚨 just baseline |
| idiosyncratic_unknown__down | +3.32 | +2.39 | **+0.93** | 🚨 just baseline |
| idiosyncratic_unknown__up | +2.83 | +2.39 | **+0.44** | 🚨 just baseline |
| rotation_flow__up | +3.71 | +2.39 | **+1.32** | 🤏 marginally above |
| **product_news__up** | **+8.15** | +2.39 | **+5.76** | 🟡 only real candidate |

Four of five "survivors" are within ~1% of baseline → they're the mega-cap drift,
not catalyst-driven edge. Same pattern that killed the cross-sectional SPY/IVV
"28 survivors" (false signal from non-edge structural reason).

## The one real candidate (and its caveats)

`product_news__up`: N=48, raw CAR +8.15% / t=3.78, **+5.76% above baseline.**
This is the only cohort that survives both the gate AND the baseline correction.

**Caveats that argue against treating it as an edge:**
- Sample is small (N=48 over 6 years = ~8 events/year).
- Effect is DECAYING: early half +10.36%, late half +4.48%. Classic anomaly-decay
  shape OR classifier-selection drift OR small-sample noise.
- "product_news__down" shows +11.27% drift on N=7 — same direction, suggests the
  positive drift here is mostly mega-cap baseline + a residual that could be real.
- After realistic transaction costs (~10-20 bps per mega-cap round-trip) and the
  challenge of identifying "product_news" events in real time, net edge would be
  closer to +5%/event = ~40%/yr gross IF the decay reverses, which it won't.

**Honest verdict on product_news__up**: a small effect that is *plausibly* the
classic "good product news → analyst upgrade wave + momentum" pattern. Real
literature exists. N is too small to deploy. The decay across OOS halves is a
red flag.

## What this Phase 2 produced (the durable output)

The catalog itself + the baseline-correction methodology. Phase 2 caught the
mega-cap beta drift trap — a class of false positive the deflated-Sharpe gate
alone would NOT have caught. **The 5-survivor headline would have been a
mirage** without the baseline check, similar to the SPY/IVV pair-trade artifact
the cross-sectional lab almost reported.

## Action

- Do NOT treat any cohort as a deployable edge.
- Keep `product_news__up` as a watchlist candidate. Re-run periodically as the
  catalog grows; if the decay reverses or the effect strengthens with more
  N, that's worth a deeper look.
- Add baseline correction to the standard Phase 2 / catalyst-study report (any
  CAR claim must report drift-minus-baseline).
- Update the dashboard scoreboard: the catalog + Phase 2 test is the 18th
  rigorous test in the campaign. Result: no genuine survivor.
