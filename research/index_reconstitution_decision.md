# Decision: S&P 500 Index Reconstitution / "Index Effect" (T39)

Pre-registration: `research/index_reconstitution_preregistration.md`. Falsify-first.
**A decayed null was the predicted outcome — and the placebo caught a would-be
artifact on top of it.**

## Verdict

### ❌ KILL — the announce→effective "index effect" is dead in 2010-2025, and the small positive add CAR is name-drift, not flow (placebo absorbs it)

## Numbers (after-cost, PRIMARY window = `car_announce_eff` = [-5, 0] trading days, additions)

| metric | value |
|---|---|
| N (usable adds) | **277** |
| gross mean CAR | **+0.48%** |
| after-cost mean (−10 bps) | **+0.38%** |
| t-stat | **+1.11** |
| median | −0.09% (below 0) |
| %positive | 49% |
| IS 2010-2017 mean (t) | +0.21% (t=+0.46), N=121 |
| OOS 2018-2025 mean (t) | +0.68% (t=+1.01), N=156 |
| **PLACEBO mean (t)** | **+0.41% (t=+2.85)**, N=1,385 random same-name windows |

Deletions (survivorship-crippled, N=67, **excluded from verdict**): announce→eff
CAR = +1.42% (t=+1.26) — wrong sign (hypothesis was negative) and unusable
because ~80% of true deletions are purged from yfinance (M&A casualties).

K-band robustness (report-only, primary is K=5): K=3 net=+0.31% t=+1.26;
K=7 net=+0.72% t=+1.79. No K reaches |t|≥2; widening the proxy lead only pulls in
more of the same name-level drift, not a sharper flow signal.

## Gate result (each line PASS/FAIL)

- **PASS**: N=277 (need ≥ 30).
- **FAIL**: after-cost signal — `car_announce_eff` net=+0.0038 (gross=+0.0048)
  t=+1.11 (need net>0 & |t|≥2.0).
- PASS: OOS sign stable — IS=+0.0021, OOS=+0.0068 (same sign, but both null).
- **FAIL**: placebo NOT null — placebo mean=+0.0041 t=+2.85 (need |t|<2.0).
- too-good tripwire: not triggered (nothing was too good; median < mean and < 0,
  which itself flags the mean as drift-inflated — handled by the placebo).

Two independent FAILs. Either alone is a KILL.

## Artifact class (if killed)

**Two stacked findings, brain/30 taxonomy:**

1. **Decayed effect / in-noise** — the headline. The classic announce→effective
   add pop (Shleifer 1986; Beneish-Whaley 1996; ~+3-7% historically) is **absent**
   in 2010-2025: gross +0.48%, t=1.11, median *below zero*, 49% positive. This is
   exactly Greenwood & Sammon's "Disappearing Index Effect" — the forced-flow
   front-run trade is crowded and gone. IS and OOS are both null; there is no
   positive effect in either era to decay *from*.

2. **Class #5 — pooled-baseline / composition (name-drift) contamination** — the
   smoking gun, and the reason the small +0.48% is not even worth a second look.
   The placebo (random non-event 5-day windows on the **same** added names) yields
   **+0.41%, t=2.85** — i.e. *larger* significance than the event windows. The
   cohort's +0.48% minus the +0.41% the same names drift in *any* random window
   leaves ≈ **+0.07%**: nothing. Newly-added S&P names are recent winners that carry
   a mild positive market-adjusted drift in every 5-day window, event or not. The
   "index effect" the raw add CAR seems to show is that composition drift, not
   forced flow. The placebo control absorbed it precisely as the pre-reg designed.

## Honest verdict (2–4 sentences)

The S&P 500 announce→effective "index effect" — the part the prior effective-date
T-study explicitly left untested — is **not tradable on free data in 2010-2025**.
The additions' announce→effective CAR is a statistically insignificant +0.48%
gross (+0.38% after costs, median below zero), and a same-name placebo earns the
*same* +0.41% (t=2.85), so even that small positive is recent-winner name drift,
not forced index-fund flow. This is a clean, double falsification (decayed effect
AND placebo-absorbed) consistent with two decades of front-running literature. It
does **not** disprove the historical (pre-2000) pop, and the deletion side remains
formally untestable on yfinance due to ~80% survivorship purge.

## Data-wall flag (read this)

**A clean, complete, free, programmatic ANNOUNCEMENT-DATE series for S&P 500
changes does not exist.** Verified directly: the Wikipedia "Selected changes"
table has only an *Effective Date* column; announcement dates survive only inside
citation `date=` fields with coverage swinging from 25/30 (2016) to **0/19 (2024)**
and **0/24 (2019)** — unusable, and a cite date is the reference's publish date,
not the S&P announcement (provenance class-4 risk). We therefore used a
**pre-registered ex-ante proxy** `t_announce = effective − 5 trading days`,
calibrated to the *median 6-calendar-day (~5-trading-day) lead* observed on the
101 Wikipedia rows that do carry both dates. The effective dates themselves
(snapshot-diff of `fja05680/sp500`) are reliable. The proxy mis-centers the window
for any change whose true lead ≠ 5 td, biasing toward a null (conservative). A
*true* announce-timestamp test needs paid data (S&P press releases / Bloomberg
INDX). This is a real data outcome, reported, not a hidden failure.

## Files

- `src/trader/catalysts/index_reconstitution.py` — pure announce→effective CAR +
  placebo + after-cost gate (reuses the proven `index_rebalance` snapshot-diff)
- `tests/financial/test_index_reconstitution.py` — 17 network-free tests (ruff clean)
- `scripts/run_index_reconstitution_study.py` — end-to-end runner (live)
- `data/index_reconstitution_results.txt` — raw run output (these numbers)

## Registry status update line (paste into brain/34)

`- ✅ **T39** Index reconstitution / "index effect" (S&P add/delete, announce→effective) — *KILL: decayed null (add CAR +0.48% gross / +0.38% net, t=1.11, median<0) AND placebo-absorbed (same-name random windows +0.41%, t=2.85 → name drift, not flow); deletions untestable (~80% yfinance survivorship); free announcement-date series does not exist, used ex-ante effective−5td proxy.*`
