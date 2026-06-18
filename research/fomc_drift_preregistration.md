# Pre-Registration: FOMC Pre-Announcement Drift (T47)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Campaign template: `research/_TEST_TEMPLATE_preregistration.md`. Universal gate:
> `brain/30_campaign_findings.md`. Registry line: T47 in `brain/34`.

## 1. Hypothesis

SPY earns a **positive abnormal return in the ~24h window immediately before a
scheduled FOMC announcement**, materially larger than its return on matched
non-FOMC days — and we test whether that famous in-sample drift **survives
after costs and out of sample**, given published evidence the effect decayed
after 2015.

## 2. Mechanism — why would this be inefficient?

Lucca & Moench (2015, *Journal of Finance*, "The Pre-FOMC Announcement Drift")
documented that since 1994 the bulk of the US equity premium accrued in the
~24 hours before scheduled FOMC statements. Candidate mechanisms: compensation
for **resolution of monetary-policy uncertainty** (a risk premium earned by
holding into the announcement), reduced-volatility "calm before the storm"
positioning, and possibly informed pre-positioning. The FOMC calendar is
**published ~a year ahead**, so the timing is knowable ex-ante — which is
exactly what makes a persistent drift puzzling and worth a survival test.

**Honest prior: decayed / small.** The anomaly was widely publicized after 2015;
several follow-ups (and the original authors' own updates) report it weakened or
disappeared once known and arbitraged. We expect a positive IS effect, a much
weaker or null OOS effect, and after a 2 bps round trip a thin or negative net.
A clean decay finding is a win.

## 3. Data + provenance

- **Instrument:** SPY (SPDR S&P 500 ETF), the most liquid US-equity proxy.
- **Source:** yfinance, **auto-adjusted daily** closes (split/dividend adjusted).
- **Construction & staleness:** daily bars; abnormal return measured close-to-
  close. No derived/parity data. SPY is alive the whole sample — no survivorship.
- **Event list (scheduled FOMC announcement days, the 2nd/decision day, 2pm ET
  statement release):** hardcoded from the Fed FOMC calendars
  (`federalreserve.gov/monetarypolicy/fomccalendars.htm` + historical pages),
  knowable ex-ante. Listed in full in §10.
- **Sample span:** IS **2015-2020**, OOS **2021-2025**.

## 4. Cohort & control definition

- **Event day (D, the announcement day):** the SPY trading day on/after each
  scheduled FOMC 2nd-day date.
- **Pre-FOMC return (the treated signal):** SPY close-to-close return on day
  **D−1** (the trading day *before* the announcement day). This is the
  Lucca–Moench "24h before the 2pm statement" window approximated at daily
  resolution: the move from the close two days before to the close the day
  before the statement captures the bulk of the pre-announcement session
  (statement lands at 2pm on D, so the D−1 close-to-close bar is entirely
  pre-announcement).
- **Control / baseline (pooled, matched-by-construction):** the mean SPY
  close-to-close return over **all non-FOMC trading days** that are not within
  ±3 trading days of any scheduled announcement (so event-window days do not
  contaminate the baseline). The treated metric is the **abnormal pre-FOMC
  return = mean(pre-FOMC day return) − mean(non-event day return)**.
- **Placebo:** K random pseudo-event dates drawn from the non-event pool; their
  "pre-day" abnormal return should be ~0 (no drift). Repeated to get a null band.

## 5. Measurement window + LOOK-AHEAD statement

- **Windows (daily, close-to-close):**
  - **`pre_fomc` = D−1 return — PRIMARY** (the pre-announcement drift).
  - `announce` = D return (the announcement-day reaction; reported, not the claim).
  - `pre2` = D−2..D−1 cumulative (robustness on a slightly wider pre-window).
- **Look-ahead audit:** the cohort is defined **solely by the published FOMC
  calendar**, which is fixed ~a year in advance. Membership of day D−1 in the
  treated set uses **no future price information** — you would have known on
  D−2's close that the next day is pre-FOMC. The pre_fomc return (D−1
  close-to-close) is fully realized *before* the 2pm-ET statement on D, so it
  contains no announcement information. This ex-ante knowability is the whole
  point of the anomaly and is **legitimate, not leakage**. The non-event baseline
  excludes the ±3-day event neighborhood so the control cannot inherit drift
  from the events it is meant to contrast.

## 6. Friction model

- **Round-trip cost:** SPY ~**2 bps** (1 bp each way; tightest-spread US ETF).
- **Application:** the pre-FOMC trade is buy-at-D−2-close / sell-at-D−1-close
  (hold one session). After-cost pre-FOMC mean = gross pre_fomc mean − 0.0002.
  After-cost expectancy is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold)

- [ ] **N ≥ 30** scheduled FOMC events with a complete pre-window.
- [ ] **After-cost** pre_fomc abnormal return positive with **|t| ≥ 2.0**
      (one-sample t on the per-event abnormal return, null = 0).
- [ ] **OOS sign stability** — IS (2015-2020) and OOS (2021-2025) pre_fomc
      abnormal means **same sign**, both N ≥ 10.
- [ ] **Pooled baseline** — abnormal = pre-FOMC mean − non-event mean (built in).
- [ ] **Placebo** — random pseudo-event pre-day abnormal mean ≈ 0 (within the
      Monte-Carlo null band; real |t| must exceed the placebo |t| distribution).
- [ ] **Too-good tripwire** — if pre_fomc Sharpe > 3 / win-rate > 85% / median
      far from mean → placebo rerun + per-event top-5 inspection before write-up.
- [ ] **Data provenance** — §3 (yfinance auto-adjusted SPY; Fed-calendar dates).

## 8. Pre-registered KILL criteria

Kill T47 if ANY holds:

- After-cost pre_fomc |t| < 2, OR after-cost mean ≤ 0.
- N < 30 usable events.
- OOS sign flip (the IS drift does not persist 2021-2025).
- Placebo absorbs it (real abnormal mean inside the placebo null band).
- Fewer than 5 events drive it (drop top-5 → effect vanishes).

## 9. Limitations

- **Daily resolution** cannot isolate the exact intraday 2pm-to-2pm window of
  Lucca–Moench; the D−1 close-to-close bar is the cleanest daily proxy and is
  unambiguously pre-announcement. A true intraday replication is a separate test.
- **beta=1 / raw return** (no market-model alpha) — SPY *is* the market, so the
  pooled non-event baseline is the natural control.
- **2020 March meeting** (scheduled Mar 17–18) was overtaken by the **emergency
  Mar 15 action**; the scheduled meeting was not held. We **exclude** the
  cancelled March 2020 event (it has no ex-ante-tradable pre-FOMC day and would
  inject COVID-crash noise). This is documented, not hidden; a sensitivity run
  including a March-2020 placeholder is reported in the decision doc.
- This tests SPY only; a single-instrument anomaly with N≈80 events has limited
  power — wide CIs are expected and part of the honest read.

## 10. Scheduled FOMC announcement dates (2nd/decision day), hardcoded

Source: Federal Reserve FOMC calendars (current + historical pages).

- **2015:** Jan 28, Mar 18, Apr 29, Jun 17, Jul 29, Sep 17, Oct 28, Dec 16
- **2016:** Jan 27, Mar 16, Apr 27, Jun 15, Jul 27, Sep 21, Nov 2, Dec 14
- **2017:** Feb 1, Mar 15, May 3, Jun 14, Jul 26, Sep 20, Nov 1, Dec 13
- **2018:** Jan 31, Mar 21, May 2, Jun 13, Aug 1, Sep 26, Nov 8, Dec 19
- **2019:** Jan 30, Mar 20, May 1, Jun 19, Jul 31, Sep 18, Oct 30, Dec 11
- **2020:** Jan 29, (Mar 18 cancelled — emergency Mar 15), Apr 29, Jun 10,
  Jul 29, Sep 16, Nov 5, Dec 16  *(7 held)*
- **2021:** Jan 27, Mar 17, Apr 28, Jun 16, Jul 28, Sep 22, Nov 3, Dec 15
- **2022:** Jan 26, Mar 16, May 4, Jun 15, Jul 27, Sep 21, Nov 2, Dec 14
- **2023:** Feb 1, Mar 22, May 3, Jun 14, Jul 26, Sep 20, Nov 1, Dec 13
- **2024:** Jan 31, Mar 20, May 1, Jun 12, Jul 31, Sep 18, Nov 7, Dec 18
- **2025:** Jan 29, Mar 19, May 7, Jun 18, Jul 30, Sep 17, Oct 29, Dec 10

Total scheduled events 2015-2025 = **87** (88 minus the cancelled Mar 2020).
Of these, 2025 events at/after this run's data cutoff are dropped for
incomplete price windows (counted, not hidden).
