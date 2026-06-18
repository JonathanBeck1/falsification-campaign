# Pre-Registration: Buyback-Announcement Drift (T41)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`).

## 1. Hypothesis (one sentence, directional, falsifiable)

Stocks that file an 8-K (Item 8.01) announcing a **new share-repurchase
authorization** earn a positive after-cost **market-adjusted cumulative
abnormal return (CAR)** over the post-announcement window [+1,+21] (and
[+1,+63]), in excess of a matched (ticker, year) non-event control.

## 2. Mechanism — why would this be inefficient?

The classic story (Ikenberry-Lakonishok-Vermaelen 1995; Vermaelen 1981) is a
**signaling + undervaluation** effect: management with private information
buys back stock when it believes the stock is cheap, and the open-market
program creates a standing source of price-insensitive demand. The behavioral
claim is that the market under-reacts to the signal, producing a multi-month
drift. The friction that could let it persist: buyback execution is gradual
(programs run for quarters), the announcement is not a hard catalyst, and small
/ mid caps that announce are under-covered.

**Honest prior: null-to-marginal.** The ILV long-run drift was strongest in the
1980s–90s value-stock subsample and has been heavily documented since; the
 subsequent literature (e.g. post-2000 replications, and the broader "anomalies
decay after publication" result of McLean-Pontiff 2016) shows the announcement
drift shrinking. The campaign has already killed PEAD (T07), IPO lockup (T12),
and four pooled-baseline catalyst artifacts (T17). Prior here is that any raw
positive CAR is **mega-cap / universe drift (artifact class #5)** plus residual
single-name drift, and dies to the matched control + costs. We expect a KILL.

## 3. Data + provenance

- **Universe (fixed by rule, no hand-picking):** every distinct US filer that
  appears in EDGAR full-text search for the repurchase-authorization phrase set
  below, forms=`8-K`, in 2015-01-01..2025-12-31, that carries Item **8.01** and
  has a yfinance-resolvable ticker with daily history covering the window.
- **Source:** SEC EDGAR full-text search (`efts.sec.gov/LATEST/search-index`,
  the same public endpoint used by `cef_events.py`) for the event list;
  yfinance daily adjusted closes for prices; SPY as the market benchmark.
  All free. SEC requests carry a descriptive `User-Agent`
  (`trader-catalyst research buyback-drift you@example.com`).
- **Phrase set (fixed, OR-union, exact phrases):**
  `"approved a share repurchase"`, `"approved a stock repurchase"`,
  `"authorized a share repurchase"`, `"authorized a stock repurchase"`,
  `"new share repurchase program"`, `"new stock repurchase program"`.
  These target *new authorizations* (not routine "the company has a repurchase
  program" boilerplate or 10b5-1 mechanics).
- **Construction & staleness:** adjusted closes (split/div) for correct
  returns. Event date = EDGAR `file_date` of the 8-K. yfinance earnings/price
  data is end-of-day, no survivorship correction applied beyond "ticker still
  resolvable" (a known limitation, §9).
- **Event/date list — ex-ante knowability:** an 8-K announcement is a public,
  timestamped filing; t0 is strictly the **next** trading session after the
  file date, so every measured return is realizable by a trader who reads the
  filing. Knowable ex-ante = a feature, not leakage.
- **Sample span:** IS 2015-01-01..2019-12-31 · OOS 2020-01-01..2025-12-31.

## 4. Cohort & control definition

- **Cohort (treated):** one event per **(ticker, calendar-quarter)** — the
  earliest qualifying 8-K in that quarter. The quarter-dedup stops a single
  multi-exhibit filing or a re-announced program from contributing several
  near-identical events and over-weighting serial repurchasers.
- **Item filter:** the filing must carry Item **8.01** (Other Events).
  Filings that **also** carry Item **2.02** (Results of Operations — i.e.
  buyback bundled into an earnings release) are **excluded** so the cohort is
  not contaminated by the earnings-announcement / PEAD effect (T07).
- **Control / baseline (two layers):**
  1. **Market adjustment:** abnormal return = stock daily return − SPY daily
     return (beta = 1).
  2. **Matched (ticker, year) placebo:** for each event ticker-year, sample
     non-event anchor dates from the same ticker in the same calendar year
     (≥ 21 trading days from any event t0) and compute the identical
     [+1,+21] / [+1,+63] CAR. This matched control absorbs the cohort's
     composition drift (artifact classes #5, #6). The claim requires the
     cohort to beat this matched control, not just beat zero.
- **Abnormal return / signal:** CAR = sum of daily (r_stock − r_SPY) over the
  event window.
- **t0:** the first trading session **strictly after** the 8-K file date
  (8-K filings can post intraday/after close; next-session entry is the
  conservative, tradeable convention).

## 5. Measurement window + LOOK-AHEAD statement

- **Windows (event time, trading days, inclusive):**
  - `car_p1_p21` = [+1, +21] — **PRIMARY** (~1 month post-announcement drift).
  - `car_p1_p63` = [+1, +63] — secondary (~3 months, the ILV horizon, scaled).
  - `car_p1_p5` = [+1, +5] — secondary (short-window reaction).
- **Look-ahead audit:** the cohort is defined entirely by the 8-K file date and
  its item codes — information public at the close of the file date. The
  measurement window starts at t0 = the **next** session, strictly after every
  piece of cohort-defining information. No day-0 return enters any CAR (this is
  the exact defect that killed PEAD in T07; here day 0 is the file date and the
  first measured day is t0 = file_date+1 session). No future information selects
  the cohort.

## 6. Friction model

- **Round-trip cost:** **15 bps** (single-name, small/mid-cap-heavy cohort;
  7.5 bps each way — wider than the 10 bps used for mega-cap T43 because this
  cohort skews smaller and less liquid). One round trip per event.
- **Application:** subtract once from each event's gross CAR; after-cost mean
  is the ONLY ranked metric. A 2× stress (30 bps) is reported as a robustness
  check, non-gating.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable events (and, for the OOS check, both halves N ≥ 10).
- [ ] **After-cost expectancy** positive with **|t| ≥ 2.0** on the PRIMARY
      window `car_p1_p21`.
- [ ] **OOS sign stability** — IS (≤ 2019) and OOS (≥ 2020) after-cost means
      same sign, both halves N ≥ 10.
- [ ] **Pooled baseline + up symmetry** — cohort CAR minus the pooled universe
      baseline; report the matched-control net effect.
- [ ] **Matched-control / placebo** — same-ticker non-event windows average
      ~0 (|t| < 2), AND cohort-minus-matched net effect has |t| ≥ 2 for a
      survive verdict.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from
      mean auto-triggers a placebo run + top-5 contributor inspection
      (remove top-5 → effect must persist) before any write-up.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY (`car_p1_p21`) |t| < 2, OR after-cost expectancy ≤ 0.
- N < 30 usable events under the fixed rules.
- OOS sign flip (IS and OOS after-cost means disagree in sign).
- Matched-control absorbs the effect: cohort-minus-matched net |t| < 2, OR the
  matched placebo itself is significantly non-zero in the cohort's direction.
- Fewer than 5 events drive the result (remove top-5 contributors → after-cost
  mean flips sign or loses significance).
- The cohort cannot be sourced from free data at N ≥ 30 with usable price
  windows → honest **DATA_WALL** (report, do not fabricate).

## 9. Limitations

- **Survivorship / delisting:** tickers that delisted or were acquired may be
  unresolvable in yfinance, biasing the sample toward survivors. A kill is
  therefore conservative (survivor bias would, if anything, inflate the raw
  drift). A survive would need a survivorship audit before being trusted.
- **Ticker-reuse risk:** EDGAR `display_names` tickers are matched to yfinance
  as-is; a recycled ticker symbol could mis-map an old event to a new company.
  Mitigated by requiring price history to actually cover the event window.
- **Coarse benchmark:** SPY beta = 1 for all names; small caps have beta ≠ 1,
  so the market adjustment is imperfect. The matched same-ticker control is the
  defense against the residual.
- A kill does NOT prove buybacks are value-destroying or that no buyback
  sub-cohort (e.g. accelerated repurchases, deep-value names) drifts — only
  that the broad, mechanically-defined announcement cohort earns no
  after-cost, control-adjusted drift over [+1,+21] in 2015-2025.
