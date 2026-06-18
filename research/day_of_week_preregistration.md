# Pre-Registration: Day-of-Week & Pre-Holiday Effects (T50)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypotheses, sample, definitions, split, friction, gate, and kill
> criteria are fixed here so a favorable specification cannot be selected after
> the fact.
>
> Campaign template: `research/_TEST_TEMPLATE_preregistration.md`. Universal gate:
> `brain/30_campaign_findings.md`. Registry line: T50 in `brain/34`.

## 1. Hypotheses (a small pre-specified family — each reported separately)

This is a **family** of textbook calendar anomalies. We register both jointly
and report each on its own line; we do NOT cherry-pick the best one.

- **(a) Monday effect / weekday seasonality.** Mean SPY close-to-close return on
  **Mondays** is abnormally **negative** (or at least materially different) vs.
  the other weekdays — the classic "weekend effect" (French 1980; Gibbons &
  Hess 1981). PRIMARY contrast: Monday mean vs. the pooled mean of Tue–Fri.
- **(b) Pre-holiday drift.** Mean SPY return on the **last trading day before a
  US market holiday** is abnormally **positive** vs. ordinary trading days
  (Ariel 1990; Lakonishok & Smidt 1988). PRIMARY contrast: pre-holiday mean vs.
  the mean of all non-pre-holiday days.

## 2. Mechanism — why might these be inefficient?

- **Monday effect:** candidate causes are **settlement timing** (historically a
  longer settlement window over the weekend changed the cost of carry), the
  weekend accumulation of (disproportionately negative) information released
  while markets are closed, and behavioral mood effects. Once T+3→T+2→T+1
  settlement compressed and the effect was widely published, the structural
  driver weakened.
- **Pre-holiday drift:** candidate causes are **thin pre-holiday liquidity** and
  short-covering / positive behavioral positioning ("holiday optimism") into a
  closed session, plus inventory effects from dealers squaring books before a
  market closure.

**Honest prior: decayed / reversed / cost-eaten.** Both are canonical examples
of anomalies that shrank, vanished, or even reversed sign after publication and
after settlement reform (e.g., the Monday effect is widely reported to have
weakened or flipped post-1990s). Critically, **any day-of-week timing rule
trades essentially every day**, so realistic round-trip costs dominate: even a
*real* few-bps daily edge is almost certainly eaten by a ~2 bps/day round trip.
A clean "decayed and/or cost-eaten" finding is the expected, honest result.

## 3. Data + provenance

- **Instrument:** SPY (SPDR S&P 500 ETF), the most liquid US-equity proxy.
- **Source:** yfinance, **auto-adjusted daily** closes (split/dividend adjusted).
  Full available history (~1993-01 to the run's data cutoff, ~2025).
- **Construction & staleness:** daily bars; returns measured close-to-close. No
  derived / parity / intraday data. SPY is alive the whole sample — no
  survivorship bias.
- **Holiday calendar:** US **NYSE** market holidays. We use the **observed
  trading calendar itself**: a "holiday" is a weekday on which SPY does **not**
  trade (a gap in the daily index that is not a weekend). The **pre-holiday day**
  is the last actual trading day immediately *before* such a gap. This is
  derived purely from which days the market was open — it requires **no future
  information** (§5). As a robustness/label cross-check the runner also carries a
  hardcoded list of standard NYSE holidays; the primary definition is the
  calendar-gap one. (`pandas_market_calendars` is not installed in this venv, so
  the gap-based definition — which is exact for SPY's own trading days — is used.)

## 4. Cohort & control definitions

- **Weekday cohorts (a):** each SPY daily close-to-close return is labeled by the
  **weekday of the day on which the return is realized** (Mon=0 … Fri=4). The
  Monday cohort = all returns realized on Mondays. The control for the PRIMARY
  Monday test = the pooled Tue–Fri returns (matched by construction: same
  instrument, same sample, mutually exclusive). We also report each weekday's
  one-sample mean and t vs 0.
- **Pre-holiday cohort (b):** the set of returns realized on **pre-holiday days**
  (last trading day before a market-closed weekday gap). Control = all
  **non-pre-holiday** trading days (pooled). Abnormal pre-holiday return =
  mean(pre-holiday) − mean(non-pre-holiday).
- **Placebo (both):** random pseudo-"effect" days drawn from the ordinary
  trading-day pool, of the same count as the real cohort, should show abnormal
  mean ≈ 0. Monte-Carlo to get a null |t| band; the real |t| must exceed it.

## 5. Measurement window + LOOK-AHEAD statement

- **Window:** single-day **close-to-close return** (the return realized *on* the
  labeled day). For weekday (a) the label is the calendar weekday — knowable
  trivially in advance. For pre-holiday (b) the label "is the next session a
  market holiday?" is knowable **ex-ante from the published exchange holiday
  calendar** (NYSE publishes holidays years ahead).
- **Look-ahead audit:** Both cohort memberships are **calendar-defined** and
  contain **no future price information**. You know on day *D−1*'s close whether
  *D* is a Monday and whether *D+1* is a market holiday. The return being
  measured (day *D* close-to-close) is realized strictly *after* the labeling
  decision and never feeds back into it. **No look-ahead** — stated explicitly
  per brain/30 artifact class #1. The gap-based holiday detection uses only the
  set of dates the market was *open*, which is itself fixed by the published
  calendar, not by prices.

## 6. Friction model — THE KEY HONESTY POINT

- A day-of-week or pre-holiday **timing rule trades a LOT**: enter and exit
  around each labeled day, i.e. effectively **daily** round trips. Costs
  therefore **dominate** any small daily edge.
- **Round-trip cost:** SPY ~**2 bps** (1 bp each way; tightest-spread US ETF).
- **Application:** the after-cost mean for a one-day timing trade = gross daily
  mean − 0.0002 per round trip. We report **gross AND after-cost prominently**
  for every effect. **After-cost expectancy is the ONLY ranked / claimable
  metric.** A real but sub-2-bps gross edge is, by construction, dead.

## 7. Pre-registered gate (ALL must hold for a claim)

Applied **per effect** (Monday; pre-holiday):

- [ ] **N ≥ 30** usable observations in the cohort (trivially met for daily SPY;
      both halves of the IS/OOS split must each have N ≥ 10).
- [ ] **After-cost** effect mean has the **hypothesized sign** with **|t| ≥ 2.0**
      (one-sample t on per-day returns vs null = 0 for the cohort, and on the
      cohort-minus-baseline abnormal for the contrast).
- [ ] **OOS sign stability** — IS (early half) and OOS (late half) cohort means
      **same sign**, both N ≥ 10.
- [ ] **Pooled baseline** — abnormal = cohort mean − matched non-cohort mean
      (built in; up/down symmetry not applicable to a single directional cohort,
      but the weekday family is its own symmetry check: a real Monday effect
      should NOT appear identically on a placebo weekday).
- [ ] **Placebo** — random pseudo-effect days abnormal mean ≈ 0; real |t| must
      exceed the Monte-Carlo placebo 95th-pct |t|.
- [ ] **Too-good tripwire** — Sharpe > 3 / win-rate > 85% / median far from mean
      → placebo rerun + per-day top-5 inspection before write-up.
- [ ] **Data provenance** — §3 (yfinance auto-adjusted SPY; calendar-gap
      holidays).

## 8. Pre-registered KILL criteria

Kill an effect (and T50 overall if BOTH die) if ANY holds **for that effect**:

- **After-cost** effect |t| < 2, OR after-cost mean has the wrong sign / ≤ 0 in
  the hypothesized direction. (We fully expect this — costs dominate.)
- OOS sign flip (the IS effect does not persist in the late half).
- Placebo absorbs it (real abnormal mean inside the placebo null band).
- The effect is present **gross** but vanishes **after cost** — recorded as
  "real-but-uncapturable / cost-eaten," which for a tradable claim is a KILL.

## 9. IS / OOS split

- **IS = early half** of the available SPY history (chronological first 50% of
  trading days).
- **OOS = late half** (last 50%).
- Rationale: these effects are famously **post-publication decayed**; an
  early/late split is the honest test of persistence. Both halves report each
  effect's mean, t, and sign; a sign flip OOS is a kill.

## 10. Limitations

- **Daily resolution, SPY only.** A single liquid instrument; the weekday means
  are tiny (a few bps) so confidence intervals are wide — part of the honest
  read, not a defect.
- **beta = 1 / raw return** — SPY *is* the market; the pooled non-cohort mean is
  the natural control, no market-model alpha needed.
- **Gap-based holiday definition** treats any non-weekend missing trading day as
  a holiday. Genuine NYSE closures (incl. ad-hoc ones like 9/11, Sandy, days of
  mourning) are correctly captured; the pre-holiday day is the session before the
  gap. Early-close half-days are still full trading days and are **not** treated
  as holidays (a documented, conservative choice). The hardcoded standard-NYSE
  list is carried as a cross-check only.
- **Settlement mechanism** (T+3→T+2→T+1) changed over the sample; we do not model
  it structurally — the IS/OOS split is the empirical proxy for "before vs after
  the regime/publication shift."
