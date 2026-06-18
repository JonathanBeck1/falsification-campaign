# Pre-Registration: Single-name IV term-structure carry (T24)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
> Universal gate: `brain/30_campaign_findings.md`. Template:
> `research/_TEST_TEMPLATE_preregistration.md`.

## 1. Hypothesis (one sentence, directional, falsifiable)

The single-name ATM IV term-structure slope (≈30d vs ≈90d) carries harvestable
information: a **vega-neutral calendar** that is short near-dated / long
far-dated vol on the steepest-contango names and the reverse on the flattest
names earns a positive after-cost return from roll-down/term-premium that
**survives over and above an unconditional short-vol stance** (i.e. the slope
adds alpha beyond short-vol beta).

## 2. Mechanism — why would this be inefficient?

Vol term premium + roll-down. When the ATM curve is upward-sloping (contango,
`slope = far_iv - near_iv > 0`), a position short the cheaper-to-carry near leg
and long the far leg, held as time passes, sees the far leg "roll down" the
curve toward the (lower) near tenor while the near leg is sold rich relative to
the realized vol it usually covers. The forced counterparty is structural
demand for longer-dated optionality (overwriters, hedgers rolling protection)
that keeps the far end sticky; the friction that could stop arbitrage is that
calendars are vega/gamma-mismatched, operationally fiddly, and bleed in vol
spikes — exactly the convexity that deters a clean arbitrage.

**Honest prior: null-to-marginal, skeptical.** The campaign has killed 19 of 19
ideas; the directly-adjacent VRP equity test (T19) failed at the mechanism
level (IV-RV↔pnl ≈ 0.01). Single-name term premium is real in level but the
*cross-sectional slope* adding tradeable alpha **after** removing short-vol beta
is the hard claim, and the prior is that it does not survive friction. Calendar
short-vol books have catastrophic left tails (vol spikes), which we will report
explicitly (max drawdown, worst day), not just the mean.

## 3. Data + provenance

- **Universe (FIXED, no post-hoc selection):** the 24 fully-collected single
  names — ADBE AMAT AMD AVGO BKNG COST CSCO GOOG GOOGL HON INTU ISRG LIN LRCX
  META MU NFLX PEP QCOM REGN TMUS TSLA TXN VRTX — **plus QQQ and SPY** as index
  references (26 roots). **AAPL, AMZN, NVDA are EXCLUDED** (still being
  collected; partial history would bias the panel).
- **Source:** owned EOD option lake at
  `$TRADER_EOD_LAKE_ROOT/root=TICKER/...`,
  collected from ThetaData. IVs via the audited Black-Scholes solver in
  `src/trader/catalysts/vol_surface_data.py` (mid = (bid+ask)/2; two-sided
  quotes only; IV band [1%, 300%]).
- **Construction & staleness:** `underlying_close` is 100% NULL in the lake (as
  documented), so spot is the yfinance daily **raw** close joined by trade_date.
  Underlying daily closes (for realized vol and the short-vol-beta control) are
  fetched once per name from yfinance and reused. Options are EOD marks: the
  calendar P&L is a mark-to-market proxy (BS-repriced ATM straddles), NOT a
  live margined book — see §9.
- **Date list:** every trade_date present in the lake for each name; knowable
  ex-ante (it is just the trading calendar). No event selection.
- **Sample span:** full lake 2022-01-01 .. 2026-06-13.
  - **IS:** 2022-01-01 .. 2024-03-31.
  - **OOS:** 2024-04-01 .. 2026-06-13.

## 4. Cohort & control definition

This is a cross-sectional ranked study (not an event study).

- **Signal (per name, per rebalance date t):** term-structure slope
  `s = far_iv(≈90d) - near_iv(≈30d)` from `term_structure()` (ATM, ±5%
  moneyness). Cross-sectionally **rank** names by `s` on each date.
- **Treated position (the TENOR/slope bet):** dollar-neutral, **vega-neutral
  per name** calendar. On each rebalance date, form a long-short book:
  - **Long leg (top tercile by slope, steepest contango):** SHORT the ≈30d ATM
    straddle, LONG the ≈90d ATM straddle, sized so the two straddles' BS vegas
    are equal → **net zero vega** at entry. This is the classic short-near /
    long-far calendar.
  - **Short leg (bottom tercile by slope, flattest/backwardated):** the mirror
    (long near / short far).
  - Equal-weight names within each tercile; the book is dollar-neutral and, by
    construction, **vega-neutral**, so its unconditional short-vol exposure is
    ~0 — this is the discipline that isolates slope-carry from short-vol beta.
- **CONTROL #1 — unconditional short-vol stance (the key control):** an
  equal-weight book that simply shorts the ≈30d ATM straddle on **every** name
  every rebalance (no slope conditioning), delta-unhedged-proxy identical
  marking. The T24 claim requires the slope book's after-cost return to be
  positive **and** to add return **over** this short-vol book (the slope book is
  vega-neutral, so if its edge ≈ the short-vol book's, the "carry" was just
  short-vol beta leaking in).
- **CONTROL #2 — placebo:** random tercile assignment (shuffle the slope ranks
  within each date) re-run K=500 times; the real long-short return must exceed
  the placebo distribution (perm p < 0.05).
- **Pooled baseline / symmetry:** report the long-tercile and short-tercile
  returns separately (up vs down slope) — if both make money the same sign, the
  "carry" is a level effect, not a slope effect (brain/30 class 5).

## 5. Measurement window + LOOK-AHEAD statement

- **Rebalance cadence:** every **21 trading days** (monthly), non-overlapping
  holding periods. Holding horizon **h = 10 trading days** (≈ 14 calendar days),
  so the ≈30d near leg keeps ~16 calendar days of life at exit — meaningful
  roll-down WITHOUT consuming the near leg to expiry.
  - **Correction note (pre-result, unit error):** the first draft wrote
    h = 21 *trading* days, which is ≈ 30 *calendar* days and therefore expires
    the ≈30d near leg at exit (near vega → 0, vega-neutral sizing degenerate,
    and ~75% of rebalances dropped on a non-positive residual tenor). This is a
    mechanical trading-vs-calendar-day unit mismatch, independent of the sign of
    any result; it was corrected to h = 10 trading days BEFORE reading any
    cross-sectional return. h < step keeps holds non-overlapping.
- **PRIMARY metric:** after-cost per-period return of the dollar-neutral
  long-short slope book, annualized and t-tested across the non-overlapping
  periods (Newey-West not required since periods are non-overlapping).
- **Look-ahead audit:** the slope at the **close of date t** uses only quotes
  observed at/before t's close; positions are formed at t's close and marked at
  the close of t+h. The underlying spot used for entry IV is the same-day close
  (a quote and its underlying are contemporaneous — no future data). Realized
  vol used only in diagnostics is computed strictly over (t, t+h]. No
  cohort-defining quantity touches post-t information.

## 6. Friction model

- **Round-trip cost:** single-name options are far wider than SPY. Each ATM
  straddle = 2 legs; a calendar = 4 option legs; entry+exit = 8 leg crossings.
  We charge **per straddle round-trip = 1.0 vega-point of IV** as the bid/ask
  half-spread proxy (i.e. you sell at IV − 0.5 vol pt, buy at IV + 0.5 vol pt),
  applied on entry and on exit, per leg. This maps to a per-leg option-price
  haircut of `0.5 vol-pt × vega`. Reported BOTH at 1× and **2×** (stress).
- **Application:** subtract once per round trip from gross P&L; after-cost
  expectancy is the ONLY ranked metric. If the result only survives at 1× and
  dies at 2×, it is graded MARGINAL at best.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** non-overlapping holding periods across the panel (we have ~50+
      monthly rebalances × 26 names; periods, not name-days, are the unit).
- [ ] **After-cost expectancy** of the slope long-short book positive with
      **|t| ≥ 2.0** on the PRIMARY metric.
- [ ] **Incremental over short-vol (KEY):** slope book after-cost mean and t
      computed on the **residual** after regressing the slope-book return on the
      unconditional short-vol book return; residual alpha must itself be > 0 with
      |t| ≥ 2. If the slope book's edge is explained by short-vol beta, KILL.
- [ ] **OOS sign stability** — IS and OOS halves same sign, both with ≥ 10
      periods.
- [ ] **Pooled baseline / symmetry** — long-tercile and short-tercile returns do
      not both carry the same sign (that would be a level effect, not slope).
- [ ] **Placebo** — shuffled-rank long-short distribution centered ~0; real
      result beats it at perm p < 0.05.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from
      mean auto-triggers placebo + top-5 period inspection + tail report.
- [ ] **Data provenance** — §3 documents source, NULL underlying, yfinance fill.

No alternative window/cadence may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost expectancy ≤ 0.
- **Incremental-over-short-vol residual alpha |t| < 2 or ≤ 0** (the carry was
  just short-vol beta — the central control).
- N < 30 non-overlapping periods.
- OOS sign flip.
- Placebo not beaten (perm p ≥ 0.05), OR long/short terciles same-sign (level
  effect).
- Result survives only at 1× friction and dies at 2× → at best MARGINAL, not a
  survivor.

## 9. Limitations

- **EOD mark-to-market proxy, not a live book.** The calendar P&L reprices ATM
  straddles from the foundation's near/far ATM IV at entry and exit; it does not
  model intra-period gamma scalping, delta hedging, early assignment, or the
  exact strikes/expirations traded. A negative result here is decisive *for this
  proxy*; a positive result would need a contract-level backtest before deploy.
- **Tenor snapping.** `atm_iv`/`term_structure` snap to the expiry nearest the
  target days; on some dates near/far may be closer than the nominal 30/90d, so
  the realized slope is a best-available approximation.
- **Vega-neutral at entry only.** The book drifts off vega-neutral as IVs and
  time move; the control for short-vol beta is therefore approximate and we also
  report the explicit regression on the short-vol book (the harder control).
- A kill does NOT prove term premium is zero in level — only that the
  *cross-sectional slope*, traded as a vega-neutral calendar net of single-name
  friction, does not add alpha over an unconditional short-vol stance in this
  panel/era.
