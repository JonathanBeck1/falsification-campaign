# Decision: Spin-off Post-Event Drift (T42)

Pre-registration: `research/spinoff_drift_preregistration.md`. Falsify-first.
**A decayed null was the predicted outcome — and the data delivered a clean,
well-powered one: the spinco forward drift is ~0 before costs and negative
after.**

## Verdict

### ❌ KILL — the Greenblatt-style spin-off drift is dead in 2015-2025: spinco 1-month market-adjusted CAR is −0.07% gross (t=−0.03), N=104, and does not beat a ~0 placebo

## Numbers (after-cost, PRIMARY window = `car_p1_p21` = [t0+1, t0+21] trading days)

| metric | value |
|---|---|
| N (usable spincos) | **104** |
| gross mean CAR | **−0.07%** |
| after-cost mean (−20 bps) | **−0.27%** |
| t-stat | **−0.03** |
| median | +0.17% |
| %positive | 52% (coin-flip) |
| IS 2015-2019 mean (t) | −0.22% (t=−0.06), N=47 |
| OOS 2020-2025 mean (t) | +0.05% (t=+0.01), N=57 |
| **PLACEBO pooled (t)** | **−0.01% (t=−0.01)**, N=513 random (name, date) windows |
| PLACEBO same-name post-event (t) | −1.57% (t=−2.24), N=515 |

Wider 3-month window (`car_p1_p63`, report-only): gross **+1.91%, t=+0.58**,
median +0.92% — positive in *direction* (the only whiff of the historical
anomaly) but nowhere near significant and inside the placebo noise band. The
PRIMARY 1-month window, where forced-selling pressure should be sharpest, is flat
to negative.

Top-5 contributor drop (`car_p1_p21`): gross **−0.47%, t=−0.24**, N=99 — removing
the 5 biggest names makes the cohort *more* negative, so there is no concentrated
real edge hiding under outliers (the opposite of an artifact-driven positive).

Friction stress (PRIMARY): net = −0.27% at 20 bps, −0.47% at 40 bps. The signal
is gross-negative, so costs only deepen the hole; no friction assumption rescues
it.

## Gate result (each line PASS/FAIL)

- **PASS**: N=104 (need ≥ 30) — well-powered, not a data wall.
- **FAIL**: after-cost signal — `car_p1_p21` net=−0.0027 (gross=−0.0007)
  t=−0.03 (need net>0 & |t|≥2.0).
- **FAIL**: OOS sign stable — IS=−0.22% (N=47), OOS=+0.05% (N=57): signs differ,
  and both halves are statistically zero — there is no effect in either era to be
  stable about.
- **FAIL**: placebo control — pooled placebo mean=−0.01% (t=−0.01, a correct
  null) AND the cohort (−0.07%) does NOT exceed it. The cohort earns no more in
  its event window than the same kind of name earns in a random window.
- too-good tripwire: **not triggered** (nothing was too good; mean ≈ median ≈ 0,
  Sharpe ~0, win rate 52%).

Three independent FAILs; any one is a KILL.

## Artifact class (if killed)

**Decayed effect / in-noise** (brain/30: "the mechanism was real historically but
no longer survives"). The Cusatis-Miles-Woolridge (1993) / Greenblatt (1997)
multi-month spinco outperformance — once a textbook forced-selling anomaly — is
**absent on free data in 2015-2025**. The 1-month CAR is −0.07% (t=−0.03), 52%
positive, median +0.17%; the 3-month is a non-significant +1.91%. This matches the
modern evidence (McConnell, Sibley & Xu and successors) that the spin-off premium
**collapsed once it became famous and arbitraged** — spin-off ETFs (CSD, 2006),
index providers fast-tracking spincos into benchmarks, and desks that anticipate
the distribution-day supply. The forced-selling mechanism still exists mechanically,
but the price impact is now absorbed fast enough that no multi-week drift remains
for a free-data, daily-bar trader.

Crucially, this is **not** a pooled-baseline / composition artifact in the T39
direction: the pooled placebo is a clean ~0 (t=−0.01), so there is no hidden
name-drift inflating the result either. The result is simply, honestly null. (The
same-name *post-event* placebo running −1.57% reflects that freshly listed spincos
tend to drift slightly negative in their first year overall — and the event window
doesn't even beat *that*, reinforcing the kill.)

## Honest verdict (2–4 sentences)

The spin-off post-event drift is **not tradable on free data in 2015-2025**: across
104 survivorship-safe spincos (Form 10-12B universe, delisted/bankrupt names like
AFIIQ and BXRXQ included), the market-adjusted 1-month CAR from the first
regular-way close is −0.07% gross (t=−0.03), −0.27% after costs, with IS and OOS
both statistically zero and sign-unstable. A pooled placebo is a correct ~0, so the
null is genuine, not a control failure, and the cohort never beats it. This kills
the live-decade version of the Greenblatt anomaly; it does **not** disprove the
historical (pre-2000) premium, and the broad 10-12B universe includes some
non-classic carve-outs (a coarseness, noted in the pre-reg) — but no reasonable
sub-slice with N≥30 would lift a t=−0.03 to |t|≥2.

## Data note (no wall — this is a real result)

Unlike T39 (no free announcement-date series) and T39's deletion arm (~80%
survivorship purge), **T42 had no data wall**: the EDGAR 10-12B full-text universe
is complete and survivorship-safe by construction (registration-based, so failed
spincos remain), and yfinance recovers the spinco first-trade date and price
history including delisted names. Of 127 filers with a ticker, 104 were usable; 18
dropped on missing yfinance prices (ticker-changed/acquired or transient
TzMissing) and 5 on glitch/edge guards. N=104 is well above the N≥30 floor — this
is an honest, well-powered NULL, not an unsourceable one. t0 = first yfinance
trading day; the PRIMARY CAR is measured from t0+1 (entry at the t0 close) so no
return inside the window defines cohort membership (the look-ahead discipline whose
absence killed T07/PEAD).

## Files

- `src/trader/catalysts/spinoff_drift.py` — pure forward-CAR + placebo + after-cost
  gate (drop-top-k robustness, IS/OOS split)
- `tests/financial/test_spinoff_drift.py` — 19 network-free tests (ruff clean)
- `scripts/run_spinoff_drift_study.py` — end-to-end runner (EDGAR 10-12B universe +
  yfinance; live)
- `data/spinoff_drift_universe.csv` — 127 spinco filers (survivorship-safe)
- `data/spinoff_drift_results.txt` — raw run output (these numbers)

## Registry status update line (paste into brain/34)

`- ✅ **T42** Spin-off post-event drift (Form 10-12B universe, forced index-fund selling) — *KILL: decayed null. Spinco 1-mo market-adj CAR = −0.07% gross/−0.27% net, t=−0.03, 52% pos, N=104 (survivorship-safe, incl. AFIIQ/BXRXQ bankruptcies); 3-mo +1.91% t=0.58 (in noise). IS −0.22%/OOS +0.05% sign-unstable & both ~0; pooled placebo clean −0.01% (t=−0.01) → genuine null, cohort doesn't beat it; top-5 drop more negative. Greenblatt anomaly arbitraged away (spin-off ETFs + index fast-tracking). No data wall, N well-powered.*`
