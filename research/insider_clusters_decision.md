# Decision: Insider Cluster Buying (T44)

Pre-registration: `research/insider_clusters_preregistration.md`. Falsify-first.
Raw run: `data/insider_clusters_results.txt`.

## Verdict

### ❌ KILL — the documented insider-cluster-buy effect does NOT replicate in a 2016–2023 free-data sample: post-cluster market-adjusted CAR is NEGATIVE (after-cost PRIMARY −1.86%, t=−0.83), the sign FLIPS across the OOS split, and the kill holds even BEFORE the (one-directional, upward) survivorship correction.

## Numbers (after-cost, PRIMARY window `car_0_p63`, market-adjusted vs SPY)

| metric | value |
|---|---|
| N (usable K≥2 events) | **121** (186 issuers; 6,676 P-buys → 207 clusters) |
| gross mean PRIMARY | **−1.46%** (t = −0.65) |
| after-cost mean PRIMARY (40 bps) | **−1.86%** (t = **−0.83**) |
| median PRIMARY | −3.33% · %pos 40% |
| IS (≤2020) after-cost PRIMARY (t) | **+0.34%** (t = +0.10), n=57 |
| OOS (≥2021) after-cost PRIMARY (t) | **−3.82%** (t = −1.27), n=64 |
| placebo (same names, non-event) PRIMARY (t) | **−4.87%** (t = −2.39) |
| drop-top-5 PRIMARY (t) | **−5.55%** (t = −3.67) |
| K≥3 stricter PRIMARY (t) | **−1.69%** (t = −0.38), n=43 |

Survivorship dropout (counted, not hidden): **84 of 207 clusters dropped** for
no yfinance price (delisted/unmatched), +2 for short window → study N=121. yfinance
purges delisted microcaps, so the surviving 121 are tilted UP — the true effect is
≤ what we measured, which makes a negative result a *strong* kill.

## Gate result (each line PASS/FAIL)

- **PASS**: N = 121 (need ≥ 30) — well-powered.
- **FAIL**: after-cost PRIMARY mean = **−1.86%**, t = **−0.83** (need > 0 **and |t| ≥ 2.0**).
  The effect has the WRONG SIGN — gross is already −1.46% (t=−0.65).
- **FAIL**: OOS sign stability — IS = +0.34% (n=57) vs **OOS = −3.82%** (n=64): the
  sign **flips** (weakly positive early → negative late), both halves N ≥ 10.
- **PASS (vacuous)**: real (−1.86%) > placebo (−4.87%) — but BOTH are negative, so
  "beating" the placebo only says the same names drift down even harder on random
  dates; there is no positive edge to capture. The placebo being negative (t=−2.39)
  is itself the smoking gun: these neglected names are in a structurally down-drifting
  pocket, and cluster timing does not rescue them.
- **Too-good tripwire**: n/a (nothing is too good — result is null/negative). The
  concentration check still ran: dropping the top-5 contributors makes the mean MORE
  negative (−5.55%, t=−3.67), confirming the negative mean is broad-based, not an
  artifact of a few bad outliers (and certainly not propped up by a few multibaggers).

## Artifact class (if killed)

**Decayed / never-replicated effect, in-noise-to-negative** (brain/30: "the mechanism
was real historically but no longer survives"), compounded by **survivorship bias that
points the wrong way for the thesis**. This is not one of the contamination artifacts
that *manufactures* a fake positive — here there is no positive to explain away. The
cluster-buy anomaly is decades-old, published, and sold by commercial screens; in this
2016–2023 sample of small/neglected names it is gone (sign-flipped OOS, negative on the
full sample). The negative placebo (t=−2.39) shows the cohort lives in a down-drifting
pocket of the cross-section; the modest "real beats placebo" gap is name-drift
arithmetic, not harvestable alpha.

## Honest verdict (2–4 sentences)

Across 121 insider-buy clusters (≥2 distinct insiders buying within 30 days, anchored
on the last buy) drawn from a systematic 2016–2023 EDGAR Form-4 grid, the stock's
forward market-adjusted CAR was **negative** at every horizon (−1.86% after cost at 3
months, t=−0.83), with the sign **flipping** from weakly positive in-sample (≤2020) to
clearly negative out-of-sample (≥2021). The documented conviction-cluster signal did
not replicate, and the survivorship the design exposes only biases the survivors UP, so
the true population effect is no better than measured. This kill does NOT prove insiders
lack information about their own firms, nor that no conditioned variant (value/liquidity
overlay, filing-date anchoring, longer holding with a hedge) could work — it shows that
a mechanical, free-data, survivorship-exposed cluster-FOLLOW strategy is not a tradeable
after-cost edge in this sample, consistent with the honest prior that a famous, screened
anomaly is arbed away.

## Files

- `src/trader/catalysts/insider_clusters.py` — pure core: Form-4 `P` cluster detection,
  market-adjusted CAR, after-cost adjustment, top-contributor drop, gate (OOS min-N).
- `tests/financial/test_insider_clusters.py` — 24 network-free unit tests.
- `scripts/run_insider_clusters_study.py` — resumable EDGAR collector (single-round-trip
  submission XML, throttled) + end-to-end runner (yfinance prices, placebo, OOS split).
- `research/insider_clusters_preregistration.md` — pre-reg (written before results).
- `data/insider_clusters_results.txt` — raw run output (this run).
- `output/catalysts/insider_clusters_buys.csv` / `..._clusters.csv` — checkpointed buys
  and detected clusters.

## Registry status update line (paste into brain/34)

`- ❌ **T44** Insider cluster buying (Form 4, ≥2 distinct insiders/30d) — *KILL: forward market-adj CAR is NEGATIVE — gross −1.46%/after-cost −1.86% (t=−0.83) at 3m; IS(≤2020) +0.34% (t=0.10) → OOS(≥2021) −3.82% sign-FLIP; same-name placebo also −4.87% (t=−2.39) so "beats placebo" is vacuous; drop-top-5 → −5.55% (t=−3.67), K≥3 −1.69% (t=−0.38). N=121 (84/207 clusters dropped to yfinance survivorship, which biases survivors UP → kill is conservative). Free EDGAR Form-4 + yfinance.*`
