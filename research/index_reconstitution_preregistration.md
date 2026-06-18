# Pre-Registration: S&P 500 Index Reconstitution / "Index Effect" (T39)

> Status: pre-registered design, written **before** collecting or inspecting
> the announce→effective CAR results. Hypothesis, sample, windows, split, gate,
> and kill criteria are fixed here so a favorable specification cannot be
> selected after the fact. Standard campaign template; universal gate per
> `brain/30_campaign_findings.md`.

## 1. Hypothesis (one sentence, directional, falsifiable)

Stocks **ADDED** to the S&P 500 earn a **positive** after-cost market-adjusted
CAR over the announcement→effective window (forced index-fund buying), and
**DELETIONS** earn a **negative** CAR over the same window — and we expect this
effect to be **decayed to ~0** in the 2010-2025 sample (front-run since the
2000s), with the OOS split designed to *show* that decay.

## 2. Mechanism — why would this be inefficient?

When S&P announces a constituent change, every S&P-500 index fund (passive AUM
in the trillions) **must** buy the addition (and sell the deletion) by the
effective close to keep tracking error ~0. That flow is **forced and
price-insensitive** and lands on **pre-known dates** (the change is announced
several days ahead). The original "index effect" (Shleifer 1986, Harris-Gurel
1986, Beneish-Whaley 1996) was a large positive announcement-to-effective pop on
adds. The counterparty is the index fund (uninformed/forced); the friction that
historically stopped arbitrage was the risk of holding a non-member.

**Honest prior: NULL / decayed.** Greenwood & Sammon ("The Disappearing Index
Effect", 2023; HBS WP 23-025) document the abnormal return around S&P 500
additions falling from ~+7% (1980s-90s) toward ~0% by the 2010s as the trade
became crowded and anticipated, and as index funds began trading more patiently.
We expect a small, statistically insignificant effect and a clean **KILL**. A
clean null *is the predicted outcome* and counts as a successful falsification.

## 3. Data + provenance

- **Instrument(s) / universe (fixed):** every S&P 500 add and (separately)
  delete with an effective date in the IS/OOS span below. No post-hoc ticker
  selection.
- **Event source:** `fja05680/sp500` GitHub repo, *"S&P 500 Historical
  Components & Changes (Updated).csv"* — full constituent snapshots 1996→present.
  We **diff consecutive snapshots** (`changes_from_snapshots`, pure, reused from
  `index_rebalance.py`, unit-tested offline) into (ticker, effective_date,
  kind) events. Reliability: **good for the fact and the EFFECTIVE date** of each
  change (cross-checked against the repo's independent 2019 change file in the
  prior T-study).
- **Announcement date — the data wall, and our pre-registered proxy.** A clean,
  complete, free, programmatic **announcement-date** series for S&P 500 changes
  **does not exist**. We verified this directly: the Wikipedia "Selected changes
  to the list of S&P 500 components" table carries only a single **Effective
  Date** column; an announcement date appears only inside citation `date=`
  fields, and those are present for just **111/352 rows** with coverage swinging
  from 25/30 (2016) to **0/19 (2024)** and **0/24 (2019)** — i.e. not a usable
  series, and a citation date is the reference's publish/access date, not
  necessarily the S&P announcement (provenance class-4 risk per brain/30). On the
  101 rows where Wikipedia *does* carry both dates, the announce→effective lead
  has **median 6 calendar days (mode 7)** ≈ **5 trading days** — the canonical
  "S&P announces ~1 week before effective". We therefore PRE-REGISTER an
  ex-ante proxy:

      t_announce  :=  effective_date − 5 trading days   (K=5, fixed)

  This is **ex-ante and look-ahead-free**: K is a fixed constant calibrated from
  an *independent* subset, not from the prices we will measure. We report the
  primary on K=5 and a robustness band K∈{3,7} (NO re-selection of K to pass).
- **Prices:** yfinance, auto-adjusted daily closes; SPY as the market proxy
  (beta=1 market adjustment, house convention).
- **Survivorship:** ADDITIONS are alive by construction (they are current/recent
  members and survive in yfinance). DELETIONS are **survivorship-crippled** — the
  prior T-study found ~81% of deletions are purged from yfinance (M&A
  casualties). We measure deletions but **exclude them from the verdict**;
  reported for completeness only.
- **Sample span:** IS (early) **2010-01-01 .. 2017-12-31** · OOS (late)
  **2018-01-01 .. 2025-12-31**. Pre-2010 excluded (the effect was already gone by
  2010 per the prior study and the literature; this study tests whether *any*
  residual announce-window flow effect survives in the modern, front-run era).

## 4. Cohort & control definition

- **Cohort (treated):** ADDITIONS with effective date in span (PRIMARY). DELETES
  measured separately, excluded from verdict (survivorship).
- **Control / baseline:** (a) market-adjusted CAR already nets out the universe
  (stock ret − SPY ret, beta=1); (b) a **placebo**: for every cohort name, draw
  random non-event 5-trading-day windows elsewhere in the same name's price
  history and compute the identical CAR — placebo mean must be ~0. This absorbs
  any name-level drift the announce window would otherwise inherit.
- **Abnormal return / signal:** AR_t = stock_ret_t − SPY_ret_t (beta=1).
- **t0 / window anchor:** the effective trading day (first trading day on/after
  the effective date); t_announce = that index − 5 trading days.

## 5. Measurement window + LOOK-AHEAD statement

- **PRIMARY window (event time, inclusive):** `car_announce_eff` =
  AR summed over `[t_announce, t_effective]` = the **[-5, 0]** trading-day window
  ending on the effective day — i.e. the forced-flow / front-running window.
- **Secondary (reported, not gated):** `car_announce_m1` = `[-5, -1]` (pure
  announcement run-up, excludes effective day); `car_eff_p5` = `[0, +5]`
  (post-effective reversal check).
- **Look-ahead audit:** The cohort is defined entirely by (ticker,
  effective_date, kind) — all **ex-ante, published facts** known on the
  announcement date by construction (S&P publicly announces the change before it
  is effective; an index fund acts on exactly this information). The proxy lag
  K=5 is a fixed constant from an independent subset, NOT fit to the measured
  prices. The measurement window `[-5, 0]` uses only returns inside that ex-ante
  window. **No information from after the effective date enters cohort
  membership or the primary signal.** This is the textbook ex-ante event study;
  ex-ante knowability is the *feature* being traded, not leakage.

## 6. Friction model

- **Round-trip cost:** single-name liquid large-cap ~**10 bps** round trip
  (5 bps each way: spread + impact), conservative for S&P 500 names. Cite: house
  convention, brain/30 (single-name ~5-10 bps).
- **Application:** subtract 0.0010 once per event from gross CAR. After-cost mean
  is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable ADD events.
- [ ] **After-cost ADD CAR** positive with **|t| ≥ 2.0** on the PRIMARY window.
- [ ] **OOS sign stability** — IS (2010-17) and OOS (2018-25) ADD halves same
      sign, both N ≥ 10 (test honestly for decay; a flip/null = KILL as predicted).
- [ ] **Pooled baseline / symmetry** — market-adjustment is the baseline;
      deletes (if any usable) should point the *opposite* sign (down) — a same-sign
      add/delete result would be a beta/drift artifact, not a flow effect.
- [ ] **Placebo** — random non-event 5-day windows on the same names show CAR ~0
      (|t| < 2); claim requires placebo null AND cohort net |t| ≥ 2.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-5 contributor inspection before any write-up.
- [ ] **Data provenance** — source, construction, the announcement-proxy and its
      data wall documented (§3).

No alternative window or alternative K may replace the PRIMARY/K=5 if the primary
gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY (ADD) |t| < 2, OR after-cost ADD CAR ≤ 0.
- N < 30 usable ADD events under the fixed rules.
- OOS sign flip or either half null (effect decayed — the predicted outcome).
- Placebo absorbs the effect (placebo |t| ≥ 2, or cohort net |t| < 2 after
  placebo subtraction).
- Fewer than 5 events drive the result (drop top-5 contributors → effect vanishes).

## 9. Limitations

- **Announcement date is a PROXY (K=5 trading days), not the true S&P
  announcement timestamp.** A clean free announcement series does not exist;
  this is the central data wall and is flagged in the report. If the true lead
  for a given change was longer/shorter than 5 trading days, our window is
  mis-centered for that event — a source of attenuation, biasing us toward a
  null (conservative). A *true* announcement-window test needs paid data
  (S&P press-release timestamps / Bloomberg INDX).
- **Deletions are survivorship-crippled** (~81% purged from yfinance) and are
  excluded from the verdict; a clean deletion test needs CRSP.
- **Beta=1 market adjustment** (house convention); added names skew large-cap /
  low-beta, so this is unlikely to manufacture a false negative.
- A KILL here does **not** disprove the *historical* (pre-2000) index effect —
  it tests only whether a tradable announce-window residual survives in
  2010-2025 on free data with a proxied announcement date.
