# Pre-Registration: 13F Institutional Cloning (T45)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`).

## 1. Hypothesis (one sentence, directional, falsifiable)

Cloning the **new/added** equity positions a set of notable institutional
managers disclose in 13F-HR filings — entering each on the **filing date** (the
only ex-ante-tradeable timing) — earns a positive after-cost market-adjusted CAR
vs SPY over the following 1/3/6/12 months.

## 2. Mechanism — why would this be inefficient?

The behavioral story: well-known managers (Berkshire, Pershing Square, Third
Point, Greenlight, Appaloosa, Baupost, Icahn, etc.) are informed; their
disclosed buys reveal high-conviction theses the crowd under-reacts to, so
followers earn drift.

**The structural reason it almost certainly fails — tested head-on:** 13F-HR is
filed **up to 45 calendar days after quarter-end** (Rule 13f-1). By the time the
holding is *disclosed*, the manager has held it for an average of ~1.5 months
already, and any information has had a full quarter-plus to be impounded. A
follower can only act on the **filing date**, not the trade date or quarter-end.
Measuring from the filing date is the honest ex-ante test, and it strips out
exactly the period in which a real informed-trading edge would have shown up.
The published "clone" literature (Cohen-Frazzini-Malloy "best ideas",
AlphaClone, GuruFocus) finds the effect is concentrated at the trade date and
heavily decayed by the disclosure date; the cheap, capacity-constrained,
crowded-by-construction filing-date version is the one a retail follower can
actually run.

**Honest prior:** null to weakly-negative after cost. The 45-day disclosure lag
is the dominant prior — this is a documented stale-information anomaly, and the
campaign has killed 18-for-18 such ideas. We test it precisely to show the lag,
not the manager skill, is the binding constraint.

## 3. Data + provenance

- **Universe (fixed, declared below):** a hardcoded list of ~12 well-known
  long-biased equity 13F filers by CIK, chosen for name recognition and a long
  filing history (no post-hoc performance selection). List frozen in the runner.
- **Source:** SEC EDGAR 13F-HR filings via `edgartools` (`edgar` 5.35.x);
  daily split/div-adjusted closes via yfinance. SEC requests carry a descriptive
  User-Agent (`TRADER_SEC_USER_AGENT`).
- **Construction & staleness:** Each filing's `infotable` is aggregated by CUSIP
  (summing `Value` across sub-manager rows), equity-long only (`PutCall` empty —
  options/puts dropped). A position is **NEW** for a filing if its CUSIP is
  absent from that manager's immediately-preceding 13F-HR. The **event date is
  the filing's `filing_date`** (ex-ante tradeable), NOT `report_period`
  (quarter-end). Prices are auto-adjusted closes (correct for returns); the only
  survivorship exposure is yfinance dropping fully-delisted tickers, which biases
  *toward* the hypothesis if anything (failed clones disappear).
- **Event/date list:** derived live from EDGAR per the frozen CIK list; fully
  reproducible and knowable ex-ante (the filing date is public the day it lands).
- **Sample span:** 13F-HR filings with `filing_date` in **2015-01-01 ..
  2024-06-30** (so a full +252-trading-day forward window to ~2025-06 exists).
  IS = filings filed **≤ 2020-12-31**; OOS = filings filed **2021-01-01 .. 2024-06-30**.

## 4. Cohort & control definition

- **Cohort (treated):** one event per (manager CIK, NEW-position ticker, filing
  date). A ticker bought by two managers in the same window is two events
  (independent clone signals), but deduplicated to one event per (ticker, filing
  date) to avoid double-counting the same forward path.
- **Control / baseline:** (a) **pooled baseline** — SPY market-adjustment is
  built into the abnormal return (beta=1), so every CAR is already cohort-minus-
  market; (b) **placebo** — for each cloned name, a random non-event trading date
  for the SAME ticker (≥ 30 trading days from any real filing event), measured
  over the identical forward windows. The placebo absorbs name-level drift; a
  real edge requires real > placebo.
- **Abnormal return / signal:** stock daily return − SPY daily return (beta=1),
  summed over the window (market-adjusted CAR).
- **t0:** the first trading day on/after `filing_date` (entry the follower can
  actually achieve; a follower reads the filing and buys at the next close).

## 5. Measurement window + LOOK-AHEAD statement

- **Windows (event time, trading days, inclusive):**
  `car_0_p21` (~1m), **`car_0_p63` (~3m) — PRIMARY**, `car_0_p126` (~6m),
  `car_0_p252` (~12m). The PRIMARY is fixed at 3 months; no alternative window
  may replace it if the primary gate fails.
- **Look-ahead audit:** The cohort is defined entirely by information public on
  `filing_date` (the 13F infotable is in the filing; "NEW vs prior filing" uses
  only the current and the previous 13F, both already public on this filing
  date). The measurement window starts at the first trading day **on/after**
  `filing_date`, strictly after all cohort-defining information. The quarter-end
  `report_period` is deliberately NOT used as t0 — using it would be the
  classic look-ahead the literature exploits and a follower cannot. Filing dates
  are ex-ante knowable (public the moment EDGAR posts them), so this is a
  feature, not leakage.

## 6. Friction model

- **Round-trip cost:** **10 bps** single-name (5 bps each way; mid-cap liquid
  names, conservative for a retail follower). Subtracted once per event from the
  gross CAR.
- **Application:** after-cost CAR = gross CAR − 0.0010. After-cost expectancy is
  the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable clone events (full +252 window available).
- [ ] **After-cost expectancy** positive with **|t| ≥ 2.0** on the PRIMARY window.
- [ ] **OOS sign stability** — IS (≤2020) and OOS (2021-24) same sign, both N ≥ 10.
- [ ] **Pooled baseline** — CAR is already SPY-adjusted (beta=1); report it.
- [ ] **Matched-control / placebo** — same-name random-date placebo ~0; claim
      requires real PRIMARY mean > placebo PRIMARY mean AND after-cost |t| ≥ 2.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-5 contributor inspection before write-up.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost expectancy ≤ 0.
- N < 30 usable events under the fixed rules.
- OOS sign flip (effect decayed / regime-dependent).
- Placebo absorbs the effect (real PRIMARY mean ≤ placebo PRIMARY mean).
- Fewer than 5 events drive the result (remove top-5 contributors → effect vanishes).

## 9. Limitations

- Beta=1 market adjustment (deliberate house simplification; no size/value tilt
  removed — a clone book is mechanically long high-beta growth at times, so a
  positive raw CAR could be beta, which the SPY adjustment only partly removes).
- yfinance survivorship: fully-delisted clone names silently drop, biasing
  *toward* the hypothesis. A kill under this bias is therefore conservative.
- 13F covers only US long equity positions ≥ $100M managers; shorts, options,
  and non-US holdings are invisible — we test the disclosed long book only.
- A kill proves the **filing-date** clone (the only retail-tradeable timing) has
  no after-cost edge. It does NOT prove the managers lack skill, nor that the
  *trade-date* (quarter-end) version is dead — only that the 45-day disclosure
  lag is the binding constraint, exactly as hypothesized.
