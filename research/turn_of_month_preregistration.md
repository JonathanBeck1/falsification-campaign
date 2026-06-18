# Pre-Registration: Turn-of-Month Effect (T48)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`). Falsify-first.

## 1. Hypothesis (one sentence, directional, falsifiable)

The mean daily close-to-close return of a broad US equity index (SPY) is
**higher** in the turn-of-month (TOM) window — the last trading day of a month
through the first three trading days of the next month — than on the remaining
("rest-of-month", ROM) trading days, by a margin that survives after costs and
out of sample.

## 2. Mechanism — why would this be inefficient?

Structural calendar flow. Around month-end and the first days of the new month,
pension contributions, 401(k)/payroll deferrals, dividend reinvestment, and
index-fund/mandate inflows hit the market on a predictable schedule. These are
price-insensitive, recurring buy flows from forced/uninformed participants. The
counterparty (a market maker or a timer) cannot easily arbitrage a diffuse,
flow-driven, low-magnitude drift without taking on overnight/calendar risk and
paying round-trip costs each turn.

**Honest prior: small / likely decayed.** The TOM effect (Ariel 1987; Lakonishok
& Smidt 1988) is one of the most-published seasonal anomalies. Post-publication
decay is widely reported (McConnell & Xu 2008 find it persisted into the 2000s
in the US, but later work shows attenuation). We **expect** a positive, possibly
significant in-sample effect and a **weaker or null out-of-sample** one. A clean
"real historically, decayed out of sample" finding is a legitimate win. We do
NOT expect a tradeable after-cost edge.

## 3. Data + provenance

- **Instrument (fixed):** SPY (S&P 500 ETF), daily.
- **Cross-check proxy (fixed):** `^GSPC` (S&P 500 index level) for a longer span,
  used only as a robustness check — NOT a separate claim. (Index level has no
  dividends, so its mean is lower; we compare TOM−ROM *within* each series, which
  the missing dividend yield affects only as a tiny common shift in both windows.)
- **Source:** yfinance (`auto_adjust=True`), via `trader.catalysts.prices.fetch_daily`.
- **Construction & staleness:** split/dividend-adjusted close; daily
  close-to-close simple returns `pct_change()`. No survivorship issue (single
  liquid instrument). No as-of lag — daily closes are final.
- **Date list:** NONE fetched. The TOM window is **calendar-defined and computed
  from the trading-day index itself** (purely from which dates have bars), so it
  is knowable ex-ante with zero look-ahead (see §5).
- **Sample span:** full available history. IS = **1993-01-29 .. 2009-12-31**
  (SPY inception is 1993-01-29); OOS = **2010-01-01 .. 2025-12-31**. The
  `^GSPC` cross-check additionally covers pre-1993 but is reported separately.

## 4. Cohort & control definition

- **Cohort (treated) = TOM window.** A trading day is in TOM iff it is one of:
  the **last trading day of its calendar month (LDOM)**, or the **1st, 2nd, or
  3rd trading day of a calendar month**. This is the common
  "{−1, +1, +2, +3}" definition (4 trading days per month turn). Membership is
  determined solely by each date's position within the trading-day calendar.
- **Control / baseline = ROM window.** Every other trading day (days 4..second-
  to-last of each month).
- **Signal:** the daily close-to-close return itself (SPY is the benchmark; this
  is a within-series timing question, not a cross-sectional abnormal return).
  PRIMARY statistic = `mean(TOM daily ret) − mean(ROM daily ret)` (the per-day
  abnormal return of being in the window), with a Welch two-sample t-test on the
  two daily-return populations.
- **t0 / convention:** returns are close-to-close; a day's return is assigned to
  the window the day belongs to (the return *realized on* that day). A long-only
  TOM timing rule holds from the prior close into each TOM day.

## 5. Measurement window + LOOK-AHEAD statement

- **Window (the 4 TOM trading days per month turn):** {LDOM, +1, +2, +3}.
- **PRIMARY metric:** per-day TOM−ROM mean daily-return difference (Welch t).
- **Look-ahead audit:** The cohort is defined **entirely by the calendar
  position of each trading day** — "is this the last trading day of the month?"
  and "is this among the first three trading days of the month?". Both are known
  with certainty at the prior day's close (the trading calendar is published far
  in advance; the only edge case, an unscheduled market closure on what would be
  the last day, is rare and does not use any return information). **No return,
  price, or future bar is used to assign window membership.** This is an ex-ante,
  calendar-defined rule — knowability is a feature, not leakage. We assign LDOM
  using each month's realized set of bars, which means we "know" the last bar of
  the month; in live trading one approximates LDOM as "the last *scheduled*
  trading day", which differs only on rare unscheduled closures. We flag this as
  a minor, non-return-based approximation in §9 (not a leakage of the dependent
  variable).

## 6. Friction model

- **Round-trip cost:** SPY ~2 bps round trip (1 bp each way; tight ETF spread +
  commission-free). A long-only TOM rule enters before LDOM and exits after the
  +3 day → **~1 round trip per month ≈ 12/yr**. Per-TOM-day cost amortized =
  2 bps / 4 days = 0.5 bp per TOM day; we report BOTH (a) gross TOM−ROM and (b)
  TOM−ROM minus 0.5 bp/day (the per-day after-cost abnormal) and (c) the
  annualized after-cost edge of a long-TOM/flat-ROM rule vs buy-and-hold.
- **Application:** after-cost expectancy is the only ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** — trivially satisfied (hundreds of TOM days); the meaningful N
      bar is **both IS and OOS TOM-day counts ≥ 100**.
- [ ] **After-cost expectancy** — TOM−ROM per-day difference, minus 0.5 bp/day,
      positive with **Welch |t| ≥ 2.0** on the FULL sample (PRIMARY).
- [ ] **OOS sign stability** — IS and OOS TOM−ROM differences SAME sign, both
      with TOM N ≥ 100 (test honestly for decay).
- [ ] **Pooled baseline** — TOM compared against the ROM pooled baseline (built
      in). Symmetry sanity: the "anti-window" (a same-size random window) should
      NOT show the same positive difference (covered by placebo).
- [ ] **Placebo** — draw many random pseudo-month-turn windows (same count of
      pseudo-LDOM dates, same {−1,+1,+2,+3} shape, but anchored on random
      in-month dates). Their TOM−ROM differences must center on ~0; the real |t|
      must exceed the 95th percentile of |placebo t|.
- [ ] **Too-good tripwire** — if the TOM annualized Sharpe of the long-TOM rule
      > 3, or the TOM win-rate by day > 85%, or any single month-turn drives a
      disproportionate share, auto-trigger top-contributor inspection.
- [ ] **Data provenance** — documented in §3.

No alternative window (e.g. {−1,+1}, or +4) may replace the PRIMARY {−1,+1,+2,+3}
if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY (full-sample) TOM−ROM Welch |t| < 2, OR after-cost per-day
  difference ≤ 0.
- IS or OOS TOM-day count < 100.
- **OOS sign flip** vs IS (effect decayed / regime-dependent) — this is the most
  likely kill given the honest prior.
- Placebo absorbs the effect: real |t| ≤ 95th-pct placebo |t|.
- A single month-turn or year drives the result (drop top contributor → effect
  vanishes).

## 9. Limitations

- Single instrument (SPY) plus one index-level cross-check; not a multi-index
  panel. A US-only finding.
- LDOM is computed from realized bars (the month's last present trading day). On
  rare unscheduled closures this differs from the ex-ante "last scheduled day";
  this is a calendar approximation, not a use of the return being predicted.
- Daily close-to-close granularity; no intraday timing, no overnight-vs-intraday
  decomposition.
- A kill does NOT prove the historical effect never existed — only that, under
  the fixed {−1,+1,+2,+3} rule on SPY, it does not survive our after-cost + OOS
  + placebo gate today.
