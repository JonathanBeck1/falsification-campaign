# Pre-Registration: Insider Cluster Buying (T44)

> Status: pre-registered design, written **before** collecting or inspecting
> the results of THIS run. Hypothesis, sample, windows, split, gate, and kill
> criteria are fixed here so a favorable specification cannot be selected after
> the fact. Supersedes the under-powered smoke run recorded in
> `research/insider_cluster_report.md` (that prior run scanned only 6
> filing-days → N=12, below its own declared sample; it is NOT the registered
> result). Slug for this run: `insider_clusters`.

## 1. Hypothesis (one sentence, directional, falsifiable)

When **>= K distinct insiders of the same issuer file Form-4 open-market
PURCHASES (transaction code `P`) within a short window** (a "cluster"), the
stock earns a positive **market-adjusted** cumulative abnormal return (CAR vs
SPY, beta=1) over the following 1/3/6/12 months, strongest in neglected /
microcap names.

* **H1 (primary):** cluster mean CAR over `[0,+63]` trading days (~3 months)
  > 0 with after-cost `|t| >= 2`.
* **H0:** cluster CAR is indistinguishable from 0 and/or from a matched/placebo
  control after costs and survivorship.

## 2. Mechanism — why would this be inefficient?

Insiders hold a genuine information advantage about their own firm; multiple
insiders buying at once ("conviction cluster") is the strongest documented
insider sub-signal (Lakonishok–Lee; Cohen–Malloy–Pomorski routine-vs-
opportunistic; Jeng–Metrick–Zeckhauser). In **neglected / microcap** names,
sparse analyst coverage and limits-to-arbitrage (illiquidity, hard-to-borrow,
small float) plausibly let the signal persist longer than in large caps where
it is arbitraged within days.

**Honest prior: null-to-small after costs.** The effect is decades-old, widely
published, and sold by commercial cluster-buy screens — exactly the profile of
an arbitraged-away anomaly. The dominant *measurement* risk is **survivorship**:
yfinance purges delisted tickers, so the microcaps that went to zero vanish from
the sample and the survivors tilt UP. A large, clean, significant result is more
likely a survivorship/look-ahead artifact than real alpha and will be treated
with suspicion, not celebration.

## 3. Data + provenance

- **Universe (fixed):** every issuer that has a qualifying Form-4 `P` cluster on
  the scanned filing-days below. No post-hoc ticker selection.
- **Source — events:** SEC EDGAR Form-4 filings (free). Fetched via a fast
  single-round-trip collector: derive the full-submission `.txt` URL from
  (CIK, accession) listed in the EDGAR Form-4 index, fetch it, and parse the
  embedded ownership XML for `nonDerivativeTransaction` rows with
  `transactionCode == 'P'`. Descriptive SEC `User-Agent` on every request,
  throttled to stay within SEC fair-access limits.
- **Source — prices:** yfinance, adjusted closes (`auto_adjust=True`), beta=1
  market adjustment vs SPY. Survivorship: yfinance drops delisted names; we
  COUNT every dropped issuer and report it, and treat the result as
  survivorship-biased UP (a one-directional optimism we flag, not correct).
- **Construction & staleness:** transaction date is the Form-4 reported
  transaction date (NOT filing date). Form-4 must be filed within 2 business
  days, so the public-knowledge date is ~0–2 trading days after the anchor; we
  anchor on the transaction date and note the ~2-day lag as a small optimism we
  do NOT correct for (a realistic follower is slightly later, so our CAR is, if
  anything, generous).
- **Event/date list (knowable ex-ante?):** the cluster anchor is the last buy
  date, which is on the public tape via the Form-4 filing within 2 business
  days — knowable ex-ante to a follower. Not look-ahead.
- **Sample span (FIXED, declared in advance):** scanning EVERY filing-day at
  full XML fidelity over 2016–2023 (~1.5–2.8k Form-4s/day) is infeasible in this
  budget, so we fix a **deterministic stratified grid: the 8th and 22nd calendar
  day of every other month (Jan, Mar, May, Jul, Sep, Nov), 2016 through 2023**
  (and the 1st/15th of those months too where they land on a trading day),
  spanning the whole period and all sectors/issuers that filed on those days.
  Concretely the runner enumerates days {1, 8, 15, 22} of months {1, 3, 5, 7, 9,
  11} for 2016–2023 and scans whichever are trading days. Days with no filings
  (weekends/holidays) yield zero and are simply empty — they do not bias
  selection. The scan list is frozen here; we will NOT expand or trim it after
  seeing results. UNTIL bound 2023-06-30 caps event dates so a full 12-month
  forward window (~to 2024-06) exists for every event. (If the frozen grid
  yields N<30 surviving K=2 events, that is an honest under-power / data-wall
  outcome, reported as such — we do NOT widen the grid to manufacture N.)
- **Runtime note:** the collector fetches the full-submission `.txt` once per
  Form-4, ~9 requests/s under the SEC fair-access throttle (~5–10 min per
  filing-day at ~1.5–2.8k Form-4s/day). The full ~130-trading-day grid is
  multi-hour, so the runner subsamples the frozen grid to a budget of N
  trading-days via a **deterministic even stride** (`--target-days N`) — this
  preserves coverage ACROSS the whole 2016–2023 span (so both IS and OOS halves
  are populated), unlike a chronological prefix. The stride is fixed
  (evenly spaced indices into the sorted frozen grid), declared here before the
  registered multi-year result, and the report states exactly which/how many
  days were scanned. Any shortfall vs the full grid is an honest coverage
  caveat, never a post-hoc favorable selection. (The 2-day 2020 COVID-window
  smoke run used to validate the pipeline is NOT the registered sample.)
- **IS / OOS split:** IS = event year <= 2020 (early), OOS = event year >= 2021
  (late). Both halves must be N>=10 for the OOS test to be meaningful.

## 4. Cohort & control definition

- **Cohort (treated):** for one issuer (keyed by issuer CIK), `>= K` DISTINCT
  insiders (unique normalized reporting-owner name) each with >=1 `P` whose
  transaction dates all fall inside a rolling `WINDOW_DAYS = 30` calendar-day
  span. Primary **K = 2**; stricter robustness arm **K = 3**. A single insider
  buying many days is NOT a cluster. Once a cluster fires, buys within
  `MERGE_DAYS = 30` calendar days of the event date are absorbed (no overlapping
  double-counting of the same wave).
- **Event date (t0 anchor):** the LAST (latest) buy transaction date in the
  cluster — a follower cannot act until the final qualifying buy is on the tape.
- **Control 1 — placebo:** for each cluster issuer, draw a random NON-cluster
  pseudo-event date for the same name (uniform within that name's price window,
  excluding +/-30 trading days around any real cluster), same CAR computation,
  fixed seed. Nets out "small-caps that happened to drift" from "cluster timing
  matters." Real primary CAR must beat placebo primary CAR.
- **Control 2 — pooled baseline:** because CAR is already market-adjusted
  (stock minus SPY), the SPY leg is the pooled baseline. We additionally report
  the placebo (same-names, non-event dates) as the composition-matched control,
  which absorbs the names' idiosyncratic drift.
- **Abnormal return / signal:** `AR_t = stock_ret_t - SPY_ret_t` (beta=1). CAR
  over `[0,+h]` = sum of daily `AR_t` from t0 through t0+h (trading days).
- **t0:** first trading day on/after the event (cluster anchor) date.

## 5. Measurement window + LOOK-AHEAD statement

- **Windows (event time, inclusive):** `car_0_p21`, `car_0_p63` (**PRIMARY**),
  `car_0_p126`, `car_0_p252`. An event is included only if its full `[0,+252]`
  window of trading data exists, so the same N is used across all horizons (no
  horizon-dependent survivorship).
- **Look-ahead audit:** the cohort is defined entirely by the cluster anchor
  date (last buy) and the transaction codes, both knowable from the Form-4 on
  the public tape within 2 business days of the anchor. The measurement window
  `[0,+h]` starts AT the anchor day (t0 = first trading day on/after anchor) and
  runs strictly forward; no post-anchor information enters cohort membership.
  The ~2-day filing lag means a realistic follower enters slightly LATER than
  t0, so anchoring at t0 is conservative-generous, not look-ahead.

## 6. Friction model

- **Round-trip cost:** single-name microcap entry+exit is expensive. We apply a
  **40 bps round-trip** (0.40%) as the headline after-cost adjustment — a
  deliberately conservative blend of commission (~0) + half-spread x2 +
  slippage for small/illiquid names; many true microcaps are worse, so 40 bps
  is a floor. After-cost CAR = gross CAR − 0.0040, applied once per event
  (one round trip per holding period).
- **Application:** the after-cost primary CAR mean and its t-stat are the ONLY
  ranked metric. (Gross is reported for context but never gated on.)

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N >= 30** usable K=2 cluster events (full `[0,+252]` window).
- [ ] **After-cost** primary `car_0_p63` mean > 0 with `|t| >= 2.0`.
- [ ] **OOS sign stability** — IS (<=2020) and OOS (>=2021) primary CAR same
      sign, both halves N >= 10.
- [ ] **Pooled baseline** — CAR is already SPY-adjusted; report it explicitly.
- [ ] **Matched-control / placebo** — same-names non-event placebo primary CAR
      ~0 (real must beat it); claim requires placebo null AND net |t| >= 2.
- [ ] **Too-good tripwire** — Sharpe-like t>3, %pos>85%, or median far from mean
      auto-triggers a placebo run + top-5 contributor inspection (drop top
      contributors; if the effect vanishes it is outlier-driven).
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY `car_0_p63` |t| < 2, OR after-cost mean <= 0.
- N < 30 usable K=2 events under the frozen grid (reported as under-power /
  DATA_WALL, not widened to chase N).
- OOS sign flip across the <=2020 / >=2021 split (effect decayed/regime-bound),
  OR either half N < 10.
- Placebo/matched-control absorbs the effect (real does not beat placebo, or
  net |t| < 2).
- Fewer than 5 events drive the result (drop top-5 contributors → effect
  vanishes), i.e. survivorship-multibagger artifact.

## 9. Limitations

- **Survivorship is the dominant known bias** and it points UP: delisted
  microcaps (the bad outcomes) are purged by yfinance, so even a positive
  surviving result is an optimistic ceiling, not a tradeable estimate. A kill
  here is therefore *strong* (the true effect is <= what we measure); a "pass"
  would still owe a survivorship-corrected and cross-sectionally-clustered SE
  follow-up before any capital.
- **Cross-sectional correlation:** cluster events on correlated small-caps in
  the same month/sector are not independent; the naive t-stat overstates
  significance. We do NOT correct for this; an honest pass would need a
  cluster-robust SE.
- **Stratified-grid sampling** captures a systematic slice of the period, not
  every cluster; N is reported honestly and a kill is scoped to the sample.
- A kill does NOT prove insiders have no information — only that a mechanical,
  free-data, survivorship-exposed cluster-follow strategy is not a tradeable
  after-cost edge in this sample.
