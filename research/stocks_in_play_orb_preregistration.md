# Pre-Registration: Stocks-in-Play 5-Minute Opening-Range Breakout (T52)

> Status: pre-registered design, written **before** collecting or inspecting
> any price, return, or P&L data. The hypothesis, sample, rules, split, gate,
> and kill criteria are fixed here so a favorable specification cannot be
> selected after the fact.
>
> Standard campaign template (see `brain/34_master_test_registry.md` and the
> universal gate in `brain/30_campaign_findings.md`).
>
> **Provenance note.** Written 2026-11-06. One coverage probe was attempted the
> same day (row counts only, no prices); it failed with HTTP 401 on placeholder
> Alpaca credentials, so **no market data of any kind has been retrieved for
> this test**. The commit adding this file must be pushed before Step 0 (§3)
> runs; that commit timestamp is this test's ordering evidence (cf.
> `PROVENANCE.md`).

## 0. Why this test, and why it is distinct

After 40 verdicts the open question is how the rare persistently profitable
discretionary day traders earn when no fixed daily-frequency rule survived.
Their common playbook is intraday momentum in **stocks in play** (names with
abnormal volume, usually on news), entered on an opening-range break with a
tight stop. Zarattini, Barbon & Aziz, *A Profitable Day Trading Strategy For
The U.S. Equity Market* (SSRN 4729284, 2024; "ZBA") codified exactly that and
report a top-20 Stocks-in-Play 5-min ORB at **+1,637% total, Sharpe 2.81, hit
ratio 48.4% (2016–2023), net of commissions** — versus Sharpe 0.48 for the same
ORB without the volume filter.

T52 is the published mechanical skeleton of discretionary momentum day trading,
run through the campaign gate, plus two pre-registered diagnostics: does the
news catalyst matter (H2), and how much does observable pre-entry context
separate good instances from bad (H3).

Distinct from T06 (index-level QQQ intraday on parity-derived spot), T17/T18
(multi-day post-news drift, direction from news category), and T51 (LLM news
interpretation). Here the unit is a single name, intraday, cross-sectionally
selected by opening volume, with direction set by price action.

## 1. Hypotheses

- **H1 (PRIMARY):** The ZBA top-20 Stocks-in-Play 5-min ORB, implemented to the
  paper's rules with realistic friction (§6), earns a positive after-cost
  **daily portfolio return** with **t ≥ 2.0** over 2016-01-04..2026-10-30, with
  the same sign before and after publication.
- **H2 (secondary):** Within the H1 cohort, trades with a pre-open news
  catalyst earn higher per-trade net R than trades without one.
- **H3 (descriptive only):** Net R rises monotonically across quintiles of a
  fixed, unfitted pre-entry context score.

Only H1 can produce a verdict. H2/H3 cannot rescue or sink it (§9).

## 2. Mechanism — why would this be inefficient?

A company-specific catalyst creates a one-day information and liquidity event
in one name. Institutions repositioning on it cannot print size at once without
impact, so they work orders over hours, and flow in the direction of the first
move persists intraday (intraday time-series momentum). The opening range is
where the first informed flow reveals direction; the breakout enters after
confirmation; the tight stop caps the loss when that flow is absent; the
end-of-day exit lets persistent flow run. Counterparties: liquidity providers
and mean-reversion traders fading the open. What could stop it being arbed:
**capacity** (20 names/day, intraday, sized at 1% risk, which is small for an
institution) and **operations** (full-market scan at 09:35, ~20 simultaneous
stop orders, intraday monitoring).

**Honest prior: null-to-marginal; friction is the likely killer.**

- **Cost model.** ZBA charge commission only ($0.0035/share), roughly 1–7 bps
  per round trip. The 10%-ATR stop makes the risk unit tiny: 1R ≈ 0.1 × ATR ≈
  20–50 bps of price for typical in-play names (ATR 2–5%). A realistic open-hour
  round trip (half-spread both sides plus stop-market slippage) of 10–30 bps is
  then ≈ 0.2–1.5R per trade. The gross edge must clear that.
- **Bar resolution.** A stop 10% of daily ATR away is routinely inside a single
  1-minute bar on a fast name, so entry-bar ambiguity (entry and stop in the
  same minute) is common, and its resolution can swing the result (§6).
- **Interest.** Per the paper's affiliations, one author is with a prop-trading
  firm and a day-trading education community. Not disqualifying; a reason to
  verify independently.
- **Decay.** Post-publication decay (McLean–Pontiff 2016) predicts a weaker
  2024+ half; the campaign's own record agrees (T47, T48).

We expect a KILL, most likely class #2 (friction-scale noise) or OOS decay.

## 3. Data + provenance

- **Universe (fixed by rule, point-in-time):** every symbol on Alpaca's
  `us_equity` asset lists, **active and inactive** (delisted names included),
  excluding ETFs/ETNs/funds, preferreds, warrants, rights, and units. ETF/ETN
  exclusion: NASDAQ Trader `nasdaqtraded.txt` ETF flag for listed symbols; for
  symbols absent from it, asset-name regex
  `\b(ETF|ETN|ProShares|iShares|Direxion|SPDR|Invesco|VanEck|Leveraged|Inverse)\b`.
  Ambiguous names are logged, never hand-curated. ADRs included.
- **Source (primary):** Alpaca Market Data, **SIP (consolidated) feed only**:
  daily bars, 1-minute bars, NBBO quotes at fill minutes, trade prints for
  ambiguous entry bars; Alpaca News (Benzinga) for H2/H3. **IEX-only data is
  not acceptable**: IEX is a small fraction of consolidated volume, so RVOL and
  OR high/low would be wrong.
- **Fallback:** one month of a paid minute-aggregate vendor that retains
  delisted tickers (e.g. Polygon), collect-then-cancel, same rules. The
  decision doc records which source was used.
- **Step 0 provenance checks (row counts only, before any P&L is computed):**
  1. SIP 1-min bars exist for 2016-01-04 and 2026-10-30.
  2. Delisted coverage: SIP 1-min bars exist for each of TWTR (2022-10-03),
     BBBY (2023-01-06), SIVB (2023-03-09), FRC (2023-04-27), ATVI (2023-10-11),
     XLNX (2022-02-11), CTXS (2022-09-28), SPLK (2024-03-15). Requirement:
     ≥ 7 of 8 present.
  3. Benzinga news returns items for 2016-01 (H2/H3 only; if coverage starts
     later, H2/H3 are restricted to the covered span and the decision doc says
     so).
  4. SIP NBBO quotes are retrievable for a sample fill minute; if not, the
     fallback half-spread (§6) applies and the decision doc says so.
- **Construction & staleness:** daily bars split-adjusted to day t's share
  basis for ATR14 and volume averages. The $5 price filter uses the
  **as-traded** 09:30 open on day t, so a later reverse split cannot qualify a
  sub-$5 stock. Intraday bars as-traded. All times ET; the 09:30 bar is the
  first regular-session minute.
- **Sample span:** IS 2016-01-04..2023-12-29 (ZBA's own sample) · OOS
  2024-01-02..2026-10-30 (post-publication).

## 4. Cohort, trade rule & controls

- **Eligibility on day t (ZBA filters 1–3, all ex-ante):** (1) 09:30 open >
  $5; (2) mean daily volume over t−14..t−1 ≥ 1,000,000 shares; (3) ATR14 over
  t−14..t−1 > $0.50; ≥ 14 prior sessions of history; not excluded by §3.
- **Relative volume:** RVOL = ORVol_t / mean(ORVol over t−14..t−1), where
  ORVol = shares traded in the 09:30–09:34 one-minute bars.
- **Cohort (treated):** eligible stocks with RVOL ≥ 1.0; the top 20 by RVOL on
  day t (ties by symbol, alphabetical).
- **Direction:** OR close > OR open → long only; OR close < OR open → short
  only; equal (doji) → no trade.
- **Entry:** stop order at OR high (long) / OR low (short), live from the
  09:35 bar through the 15:59 bar; unfilled → no trade.
- **Exit:** stop loss at 10% × ATR14 from the executed entry price; otherwise
  exit at the 15:59 bar close. No targets, no trailing, no overnight.
- **Sizing (ZBA):** shares = floor(0.01 × E / (0.10 × ATR14)), capped at
  notional ≤ E × 4 / 20 per position. ZBA state a 4× leverage cap but not how
  it is allocated; the even per-slot split avoids path dependence. E =
  start-of-day equity, reset daily.
- **Units:** per-trade **net R** = net P&L / (shares × 0.10 × ATR14).
  **Daily portfolio return (PRIMARY series)** = Σ net P&L / E; days with zero
  trades contribute 0.
- **Controls:**
  1. **Pooled baseline (step 5), "ORB Base":** the identical rule on a seeded
     random sample of 20 eligible, non-cohort stocks per day (seed 52).
  2. **Matched (ticker, year) permutation (step 6a):** for each cohort trade,
     the cell is the net R of the identical rule on up to 10 seeded non-cohort
     eligible days of the same ticker in the same calendar year. 2,000
     permutations, seed 52, one-sided in the hypothesized direction.
  3. **Random-entry placebo band (step 6b):** for each cohort stock-day, a
     seeded coin-flip direction and entry at the close of a seeded uniform
     minute in 09:35–10:29 (plus half-spread), same stop and EOD exit.
  4. **Up/down symmetry:** long and short legs reported separately, each
     against its own ORB-Base leg.

## 5. Measurement window + LOOK-AHEAD statement

- **Window:** intraday only; entries ≥ 09:35, exits ≤ the 15:59 bar close.
  PRIMARY = daily portfolio net return, 1× friction, full sample.
- **Look-ahead audit:** every input to selection and direction is known by
  09:35:00 on day t: the 09:30–09:34 bars, the 09:30 open, and the prior 14
  sessions' volume, ATR, and ORVol. Orders can fill only from 09:35. The
  universe is point-in-time and includes later-delisted names. RVOL never uses
  any volume after 09:34:59. H2 uses news `created_at` only (never
  `updated_at`), strictly before 09:30 ET. The cohort requires a full-market
  scan at 09:35, which a live SIP feed supports, so the rule is realizable.

## 6. Friction model

- **Commission:** $0.0035/share per side, $0.35 minimum per order (ZBA's
  IBKR-Tiered rate plus order minimum). Regulatory fees ignored (< 0.3 bps).
- **Spread:** half the SIP NBBO quoted spread at each fill (median quote within
  the fill minute). Fallback if quotes are unavailable: half-spread =
  max($0.01, 5 bps of price).
- **Entry fill (long; short mirrors):** max(OR high, entry-bar open) +
  half-spread, so a gap through the stop fills worse.
- **Stop fill (long; short mirrors):** min(stop, bar open) − half-spread −
  0.5 × quoted spread (stop-market slippage).
- **EOD fill:** 15:59 bar close ∓ half-spread.
- **Entry-bar ambiguity:** if the entry bar also breaches the stop, resolve the
  order with SIP trade prints in that minute; if prints are unavailable, assume
  stopped out. Report the share of trades affected. (Later bars are
  unambiguous: the bracket has no target.)
- **Short borrow:** not modeled (no point-in-time borrow data); hence the
  long-leg requirement in §8.
- **Levels:** 0× = ZBA (commission only) · **1× = PRIMARY** (all of the above)
  · 2× = spread and slippage doubled (stress). Report the break-even friction
  multiple.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **Step 0 provenance** (§3) passes, else DATA_WALL and stop.
- [ ] **N ≥ 30** — trivial here (≈ 2,729 trading days; tens of thousands of
      trades expected). The binding constraint is coverage, not N. Minimum
      detectable full-sample Sharpe at t = 2 ≈ 0.61 (t ≈ Sharpe × √10.8 yr).
- [ ] **After-cost (PRIMARY):** daily portfolio net return at 1× friction,
      mean > 0 and t ≥ 2.0.
- [ ] **OOS sign stability:** IS (2016–2023) and OOS (2024–2026-10) daily net
      means the same sign, both halves ≥ 10 days.
- [ ] **Pooled baseline:** cohort per-trade net R minus ORB-Base net R > 0;
      long and short legs reported.
- [ ] **Matched-control permutation:** p < 0.05 AND per-trade net |t| ≥ 2.
- [ ] **Random-entry placebo band:** observed per-trade |t| > placebo |t|.
- [ ] **Too-good tripwire** on the PRIMARY daily series
      (`periods_per_year=252`): any flag → by-hand inspection of the top-5 days
      and top-5 trades before write-up. ZBA's own 2.81 sits just under the 3.0
      line; a replication above 3 is presumed a fill-model or data error until
      shown otherwise.
- [ ] **Data provenance:** §3 documented; source recorded in the decision doc.

**Implementation.** Per-trade net R through `trader.research.gate.evaluate_gate`
with `cost_per_trade=0.0` (costs are already trade-specific in net R),
`baseline_mean` = ORB-Base mean, `placebo_cells` = matched cells, `placebo_t` =
random-entry t, `preregistered=True`, `provenance_documented=True` only if
Step 0 passed. The PRIMARY daily series through `gate_after_cost(daily, 0.0)`,
`gate_oos_sign_stability(daily_IS, daily_OOS)`, and
`too_good_tripwire(daily, periods_per_year=252)`. Both sets must PASS.

No alternative may replace the PRIMARY if it fails: the paper's 15/30/60-min
ORBs, other RVOL thresholds, top-N other than 20, and other stop multiples are
**not** tested here. Any of them is a new pre-registration, evaluated only on
data dated after its own commit.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- PRIMARY daily net mean ≤ 0, or t < 2, at 1× friction.
- OOS (post-publication) sign flip.
- Matched (ticker, year) permutation p ≥ 0.05: the "edge" is which names
  get selected, not the fact that they are in play (class #6).
- Random-entry placebo |t| ≥ observed |t|: the payoff comes from the bracket's
  shape, not the signal.
- Cohort per-trade net R ≤ ORB Base.
- Removing the top-5 days flips the PRIMARY mean's sign or drops t below 2.

Non-kill outcomes:

- **MARGINAL:** passes at 1× but fails at 2×; OR passes only through the short
  leg (borrow unmodeled); OR the long leg alone fails after cost.
- **DATA_WALL:** Step 0 fails (no SIP, or ≥ 2 of 8 delisted probes missing)
  and no fallback vendor is used.
- **SURVIVE (watchlist only):** every gate passes at 1× and 2×, the long leg
  alone passes after cost, IS and OOS agree in sign, Step 0 clean. Even then
  the next step is a new pre-registered forward paper test; no live capital on
  this result alone.

## 9. Secondary diagnostics (cannot change the H1 verdict)

- **H2 — news catalyst.** Catalyst = ≥ 1 Alpaca/Benzinga item with the ticker
  in `symbols` and `created_at` in [16:00 ET prior session, 09:30 ET day t),
  excluding items tagging > 3 symbols and headlines matching
  (case-insensitive)
  `stocks? (moving|to watch)|movers|(pre-?market|mid-?day|after-?hours) (gainers|losers|session|movers)|top (gainers|losers)|shares are trading (higher|lower)|why .* (is|are) (trading|moving|up|down|higher|lower)`
  (reaction roundups, not catalysts). Statistic: Welch t of per-trade net R,
  catalyst minus no-catalyst. Supported only if t ≥ 2.5 (raised for multiple
  secondaries) with the same sign in IS and OOS.
- **H3 — context gradient.** Within eligible stock-days with RVOL ≥ 1.0
  (seeded sample of ≤ 100 per day, seed 52), a composite score at 09:35 = the
  mean of cross-sectional percentile ranks of RVOL, |gap| (09:30 open / prior
  close − 1), OR range / ATR14, and the catalyst flag. No weights are fit.
  Report mean net R by score quintile, the Q5−Q1 Welch t, and Spearman ρ across
  quintiles. H3 estimates how much observable pre-entry context separates good
  instances from bad, a **lower bound** on what a human filter adds (tape and
  Level-2 features are absent). A Q5 cohort may become its own test only via a
  new pre-registration evaluated on data after that commit.

## 10. Limitations

- One-minute bars cannot resolve a 10%-ATR stop on fast names; trade prints
  fix only the entry bar, and the fallback is deliberately conservative.
- No borrow or locate data: hard-to-borrow small caps in play may be
  unshortable, so short-leg results are overstated.
- The 4× leverage allocation is our choice; ZBA leave it unspecified.
- Alpaca SIP is not ZBA's CRSP + IQFeed. The 0× run is a sanity check on sign
  and order of magnitude, not a target: **no parameter may be adjusted to bring
  the replication closer to the paper.**
- Survivorship is verified by a fixed 8-name probe, not a full delisting audit.
- A kill does NOT prove discretionary momentum day trading has no edge. It
  shows that its published mechanical skeleton, with these exact rules and
  realistic friction, does not survive. The human layers (selection beyond
  these features, discretionary exits, sizing up on the best days) remain
  untested; H3 bounds only the observable part.
