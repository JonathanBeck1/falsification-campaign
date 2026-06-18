# Pre-Registration: Spinoff Post-Event Drift (T42)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`). Slug: `spinoff_drift`.

## 1. Hypothesis (one sentence, directional, falsifiable)

US corporate spin-offs (the spun-off "spinco") earn a **positive after-cost
market-adjusted CAR** over the first ~1–3 months of independent regular-way
trading, versus a matched (sector/size) control, because forced index-fund and
mandate-driven selling at the moment of distribution temporarily underprices the
spinco (the Greenblatt / Cusatis-Miles-Woolridge spin-off anomaly).

## 2. Mechanism — why would this be inefficient?

**Forced / indiscriminate selling.** When a parent distributes spinco shares
pro-rata to holders, large blocks land in the hands of investors who do not want
them: (a) index funds that hold the parent for index reasons but the spinco is
not (yet) in their index, so they must sell mechanically; (b) institutions with
size/sector/charter mandates the spinco violates; (c) retail who receive an odd
small position and dump it. This price-insensitive supply at distribution can
push the spinco below fair value; informed buyers are slow because the spinco is
newly listed, under-covered by sell-side analysts, and absent from screens. The
classic studies (Cusatis, Miles & Woolridge 1993; Greenblatt *You Can Be a Stock
Market Genius* 1997; McConnell & Ovtchinnikov 2004) document multi-month
spinco outperformance.

**Why it might NOT survive:** the anomaly is famous and old. Index providers now
fast-track spincos, "spin-off ETFs" (CSD, launched 2006) explicitly arbitrage
it, and McConnell et al. and later work find the excess return **concentrated
pre-2000 and largely gone afterward**. Forced selling is also a one-time flow
that modern desks anticipate. So the live-decade (2015–2025) prior is that the
drift has decayed toward zero, especially after costs on a newly listed,
wider-spread name.

**Honest prior:** small / null. Real and large historically; most recent
evidence says decayed. Expect a KILL in the spirit of T12 (lockup), T39 (index
effect), T43 (earnings premium) — documented anomalies that died after
anticipation + costs.

## 3. Data + provenance

- **Universe (fixed, survivorship-safe):** every distinct filer of an SEC
  **Form 10-12B** (initial registration of a security class, the form a spin-off
  uses to register the spinco) with a primary 10-12B filed **2015-01-01 ..
  2025-06-30**, deduped to the earliest 10-12B per CIK. The 10-12B universe is
  *registration*-based, so it INCLUDES spincos that later did badly or delisted
  (e.g. Armstrong Flooring `AFIIQ`, in bankruptcy) — survivorship is captured by
  construction. Source: EDGAR full-text search API
  (`efts.sec.gov/LATEST/search-index`, `forms=10-12B`), descriptive
  `User-Agent` with contact email per SEC policy.
- **Ticker map:** the spinco ticker is read from the filer's `display_names`
  field in the EDGAR result (the current SEC ticker→CIK mapping). Filers with no
  ticker in the mapping are counted as dropped (not silently hidden).
- **Prices:** yfinance, `auto_adjust=True` (split/dividend adjusted) daily
  closes for spinco and **SPY** (market proxy). Construction: market-adjusted
  abnormal return, beta=1 (the conservative house convention used in the lockup /
  index / earnings studies).
- **t0 (first regular-way day):** the **first available yfinance trading day**
  for the spinco. yfinance's first print may be a *when-issued* day a few
  sessions before regular-way; to avoid that contamination the entry is taken at
  the **t0 close** and the PRIMARY CAR is measured strictly **forward from t0+1**.
  A `t0+0` (buy first close, measure from open) variant is reported for
  robustness only.
- **Filtering knowability:** the 10-12B filing date is known ex-ante; the spin
  *completion* (first-trade) date is observable on the day it happens. t0 is the
  first day the spinco trades — there is no look-ahead because membership in the
  cohort ("a spinco that began trading") is determined entirely by information
  available at/ before t0. See §5.
- **Sample span:** spincos whose **first-trade date** falls 2015-01-01 ..
  2025-03-31 (leaves ≥ ~2 months of post-t0 prices for the longest window before
  the 2025-06 data edge). IS = first-trade year ≤ 2019; OOS = ≥ 2020.

## 4. Cohort & control definition

- **Cohort (treated):** spinco names with a usable price series spanning the full
  measurement window around t0 (see §5), one observation per spinco.
- **Control / baseline (TWO disciplines, both pre-registered):**
  1. **Market adjustment:** every CAR is spinco return − SPY return (removes the
     common market move; the baseline a buy-and-hold of SPY would earn over the
     same window).
  2. **Placebo / matched-control:** a **pseudo-event placebo** — for each spinco
     name, draw random non-event windows of the same width from the **same
     name's later history** (≥ 60 trading days after t0, so the draw is outside
     the event window) and from a **pooled pool of random (name, date) windows**.
     A real forced-selling edge must appear at t0 but NOT in these random
     same-name / pooled windows. Net edge = cohort mean − placebo mean.
- **Abnormal return / signal:** `spinco_ret − SPY_ret`, summed over the window.
- **t0:** first regular-way trading day (first yfinance day); CAR measured from
  t0+1 (PRIMARY). One value per spinco.

## 5. Measurement window + LOOK-AHEAD statement

- **Windows (event time, trading days, inclusive), t0 = first-trade day:**
  - `car_p1_p21` = [t0+1, t0+21]  → **PRIMARY** (~1 month forward drift)
  - `car_p1_p63` = [t0+1, t0+63]  → ~3 month (the Greenblatt holding horizon)
  - `car_p0_p21` = [t0+0, t0+21]  → includes first-day move (robustness only)
- **Look-ahead audit:** The cohort is "names that filed a 10-12B and subsequently
  began regular-way trading." Both facts are knowable **at or before t0**: the
  10-12B is public weeks earlier, and the first-trade day is observed the moment
  it occurs. The PRIMARY return window starts at **t0+1**, strictly after t0, so
  no day inside the measurement window is used to define cohort membership. The
  entry is the **t0 close** — a price an investor could actually transact at — so
  there is no use of future information. This is the discipline whose absence
  killed T07 (PEAD): there the cohort was defined by a day-0 return that the CAR
  also included; here cohort membership uses no return at all, only the existence
  of a first-trade day.

## 6. Friction model

- **Round-trip cost:** **20 bps** (0.0020). A newly listed spinco is wider and
  thinner than an S&P constituent; the index/lockup studies used 10 bps for
  liquid large-caps — a spinco deserves at least double. One round trip
  (buy at t0 close, sell at window end) is subtracted once from the gross mean.
- **Application:** after-cost expectancy is the ONLY ranked metric. A 2× (40 bps)
  stress is reported alongside.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable spincos.
- [ ] **After-cost expectancy** positive with **|t| ≥ 2.0** on the PRIMARY window
      (`car_p1_p21`).
- [ ] **OOS sign stability** — IS (≤2019) and OOS (≥2020) halves same sign, both
      N ≥ 10.
- [ ] **Pooled baseline** — already built in via market adjustment; additionally
      the cohort mean must exceed the placebo mean.
- [ ] **Matched-control / placebo** — same-name + pooled random-window placebo is
      ~0 (|t| < 2); claim requires placebo null AND net cohort |t| ≥ 2.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-5 contributor inspection before write-up.
- [ ] **Data provenance** — EDGAR 10-12B + yfinance, documented (§3).

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost expectancy ≤ 0.
- N < 30 usable spincos under the fixed rules → if the data genuinely cannot be
  sourced free, that is an honest **DATA_WALL**, not a kill.
- OOS sign flip (effect decayed / regime-dependent).
- Placebo/matched-control absorbs the effect (net |t| < 2).
- Fewer than 5 spincos drive the result (remove top-5 contributors → effect
  vanishes), OR a data glitch (>75% one-day abnormal return) drives it.

## 9. Limitations

- **Ticker mapping coarseness.** The spinco ticker comes from EDGAR's *current*
  display name; a spinco that later changed ticker or was acquired may be
  unmappable in yfinance → dropped (counted). This is a missingness, not a bias
  toward winners (delisted/bankrupt spincos like AFIIQ remain in-sample when
  yfinance has their history).
- **10-12B ≠ spin-off perfectly.** A handful of 10-12B filers are carve-outs /
  re-registrations rather than classic pro-rata spins; the first-trade + price
  filter removes those that never traded. The universe is *registration*-based,
  deliberately broad and survivorship-safe, at the cost of some non-spin noise.
- **When-issued contamination** of the very first print is mitigated by entering
  at the t0 close and measuring from t0+1, but not fully eliminated.
- **Market-only adjustment** (beta=1, no size/value/sector factor model) is the
  conservative house convention; a true factor-neutral CAR could differ, but if
  even the crude market-adjusted CAR is null/negative after costs the richer
  control will not rescue it.
- A KILL here does NOT prove the spin-off anomaly never existed — it tests
  whether the **2015–2025, free-data, after-cost** version survives the gate.
