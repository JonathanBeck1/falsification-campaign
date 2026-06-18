# Pre-Registration: Sell-in-May / Halloween Indicator (T49)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, season definition, split, gate, friction, and
> kill criteria are fixed here so a favorable specification cannot be selected
> after the fact.
>
> Standard campaign template (see the universal gate in
> `brain/30_campaign_findings.md`). This is a calendar/allocation backtest, not an
> event-cohort study, so the "cohort/control" machinery is adapted: the cohort is
> the set of *winter* (Nov–Apr) monthly returns, the control is the set of
> *summer* (May–Oct) monthly returns, and the strategy under test is a seasonal
> allocation vs buy-and-hold.

## 1. Hypothesis (one sentence, directional, falsifiable)

US equity (SPY) returns in the **winter** half (Nov–Apr) exceed returns in the
**summer** half (May–Oct), and a seasonal allocation that holds SPY Nov–Apr and
sits in cash/T-bills May–Oct delivers a **higher Sharpe ratio than buy-and-hold
SPY after costs** over the full sample.

## 2. Mechanism — why would this be inefficient?

Proposed behavioral/liquidity story: seasonal risk appetite and liquidity —
year-end bonus/pension inflows, the "January effect," lower summer market
participation, and a documented "summer doldrums" lull. The honest counter is
that this is one of the most-publicized calendar anomalies on Earth (Bouman &
Jacobsen 2002), so if any edge existed it should be heavily decayed — and even if
winter > summer in *total* return, that is **trivially expected** of a strategy
that is only in the market ~half the time and therefore carries roughly half the
beta. The economically meaningful question is **risk-adjusted** (Sharpe) after
costs, not total return or drawdown.

**Honest prior:** Null-to-marginal on risk-adjusted edge. We expect winter mean
monthly return > summer (the seasonal split itself is real and somewhat robust in
the literature), but we expect the seasonal *strategy* to win on lower volatility
/ lower drawdown (a beta-reduction artifact), **not** on Sharpe. Decayed and/or
exposure-driven is the base case. A clean "lower exposure, not alpha" finding is a
win.

## 3. Data + provenance

- **Instrument (fixed):** SPY only (single instrument; no universe selection).
- **Source:** yfinance, daily, `auto_adjust=True` (split/dividend-adjusted total
  return close). Full available history (SPY inception 1993-01-29 → run date).
- **Construction & staleness:** Adjusted close → daily simple returns. No derived
  / parity series, no survivorship issue (single surviving ETF). One series, one
  provider.
- **Risk-free proxy for out-of-market months (fixed, conservative):** flat
  **0%/yr** while in cash (the conservative choice — a positive T-bill yield would
  only *help* the seasonal strategy, so 0% is the hardest test). A secondary
  sensitivity at a flat **2%/yr** (≈ 0.0167%/mo) is reported but is NOT the
  primary; the gate is judged at 0%.
- **Season definition (fixed, calendar, ex-ante):** a calendar month is **winter
  (in-market)** if its month number ∈ {11, 12, 1, 2, 3, 4}; **summer
  (out-of-market)** if ∈ {5, 6, 7, 8, 9, 10}. The classic "Halloween indicator":
  buy at the close of Oct 31, sell at the close of Apr 30. Implemented at monthly
  granularity (a month is wholly in or out). This is purely calendar-defined and
  fully knowable in advance — see §5.
- **Sample span:** full history; **IS = early half, OOS = late half**, split at
  the median calendar date of the available monthly series (reported exactly in
  the result).

## 4. Cohort & control definition

- **"Cohort" (treated):** winter monthly SPY returns (months 11,12,1,2,3,4).
- **"Control":** summer monthly SPY returns (months 5,6,7,8,9,10).
- **Seasonal-difference statistic:** Welch two-sample t-test on monthly returns,
  winter mean − summer mean. This is the seasonal effect's significance.
- **Strategy under test:** monthly-rebalanced allocation = SPY return in winter
  months, risk-free (0%) in summer months; benchmark = buy-and-hold SPY.
- **Signal/return convention:** monthly simple returns compounded; the strategy
  pays a round-trip cost twice per year (enter at Oct-close, exit at Apr-close).

## 5. Measurement window + LOOK-AHEAD statement

- **Granularity:** monthly returns over the full sample; the strategy holds SPY
  or cash by calendar month.
- **Look-ahead audit:** the season membership of every month is fixed by the
  **calendar month number alone** — it is known years in advance and uses **no
  price, return, or any data realized during or after the month**. There is zero
  look-ahead: the allocation for month *m* is decided ex-ante by `m ∈ winter?`.
  The IS/OOS split is on calendar date only. This is the cleanest possible
  ex-ante rule; the only "information" used is the date.

## 6. Friction model

- **Round-trip cost:** SPY ~**2 bps** per round trip (1 bp each way; liquid ETF).
- **Trade cadence:** the seasonal strategy trades **twice per year** (one exit
  Apr-close → cash, one entry Oct-close → SPY). So annual friction ≈ 2 bps × 1
  round trip = **~2 bps/yr**, i.e. essentially negligible. Buy-and-hold pays one
  entry cost over the whole sample (ignored / one-time). Cost is subtracted from
  the seasonal strategy's annual return; we note explicitly that cost is too small
  to be the deciding factor here (this is a low-turnover strategy — the friction
  gate is easy to pass and is NOT where this idea lives or dies).
- **Application:** after-cost seasonal Sharpe and after-cost annualized return are
  the ranked metrics; the comparison vs buy-and-hold Sharpe is the decisive test.

## 7. Pre-registered gate (ALL must hold — adapted from brain/30)

- [ ] **N ≥ 30** monthly observations in each season (trivially met on full SPY
      history; stated for completeness).
- [ ] **Seasonal difference real** — Welch t-test on (winter − summer) monthly
      returns has **|t| ≥ 2.0** with winter > summer (one-sided direction
      pre-registered).
- [ ] **Risk-adjusted edge (THE decisive gate)** — after-cost **seasonal Sharpe >
      buy-and-hold Sharpe** by a margin that is not trivially small. We require the
      seasonal annualized Sharpe to **exceed** buy-and-hold's. If the seasonal
      strategy merely matches or trails B&H Sharpe while showing lower vol, the
      idea is classified **risk-reduction, not alpha** → KILL as edge.
- [ ] **OOS sign stability** — the winter−summer monthly difference has the **same
      sign** in IS and OOS halves, both halves N ≥ 10; AND the Sharpe-vs-B&H
      verdict does not flip sign across halves.
- [ ] **Exposure control (the key check)** — report time-in-market (~50%) and the
      strategy's realized beta to SPY; if the entire return gap is explained by
      reduced exposure (seasonal Sharpe ≈ B&H Sharpe), conclude **lower exposure,
      not edge**.
- [ ] **Too-good tripwire** — seasonal Sharpe > 3 OR seasonal annual return >
      buy-and-hold while *also* lower vol *and* |t| of difference > 5 auto-triggers
      a re-inspection (decadal stability, top-month contributors) before write-up.
- [ ] **Data provenance** — SPY/yfinance adjusted close, documented in §3.

No alternative season definition (e.g. shifting the boundary months, adding a
MACD timing overlay, or switching to a different index) may replace the
pre-registered Nov–Apr / May–Oct split if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea **as a risk-adjusted edge** if ANY holds:

- After-cost **seasonal Sharpe ≤ buy-and-hold Sharpe** (the strategy wins, if at
  all, only by holding less market — risk reduction, not alpha).
- Winter−summer monthly-difference **|t| < 2** (the seasonal split itself is
  in-noise on this sample).
- **OOS sign flip** of the winter−summer difference, OR the Sharpe-vs-B&H verdict
  flips across IS/OOS halves (decayed / regime-dependent).
- N < 30 monthly obs in either season (not expected to bind).

## 9. Limitations

- A kill of the **risk-adjusted** claim does NOT prove winter ≯ summer in raw
  mean; the seasonal split can be statistically real while offering no Sharpe
  edge — that is in fact the expected outcome.
- Monthly granularity slightly idealizes execution (exact Oct-31 / Apr-30 closes
  via month-end bars); intra-month timing variants are out of scope by pre-reg.
- 0% risk-free is conservative; a realistic T-bill yield would *raise* the
  seasonal strategy's return and Sharpe, so a kill at 0% is the harder, fairer
  test against the strategy and a pass at 0% would be revisited at a live yield.
- Single instrument (SPY); no claim about international "sell in May" variants.
- Tax and bid/ask beyond the 2 bps stylized cost are ignored; given ~2 trades/yr
  this is immaterial to the verdict.
