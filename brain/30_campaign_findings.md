# Brain 30 — Campaign Findings: 19 Tests, 19 Kills, and the Artifact Taxonomy

Date: 2026-06-11
Status: COMPLETE (A3 verdict incorporated from the Phase 1 engine audit).

This is the consolidated record of the edge-search campaign (May 18 –
June 11, 2026). Source of truth: `brain/decisions/`. Purpose: (a) one place a
future contributor — human or agent — reads before claiming any edge, (b) the
artifact taxonomy and mandatory gate checklist that every future survivor
claim must pass.

## Headline

**No broad systematic edge was found in public data on liquid instruments.**
Every statistically promising result, without exception, was eventually
explained by an artifact. The durable assets are the falsification machine,
the data infrastructure, and this taxonomy.

## The test ledger

| # | test | verdict | killed by |
|---|---|---|---|
| 1 | Iron condor, ThetaData intraday sweep (72 configs, SPY) | no edge | every config lost; plumbing validated |
| 2 | Iron condor cross-regime QQQ 2020/2021/2022 (honest engine) | no edge | classic condor failure: wins small, loses big; 2022 realistic = −$42/25 trades |
| 3 | Richer QQQ option features (GEX, vol-of-vol, 25d skew, flow, term curvature) | no edge | nothing survived friction + OOS |
| 4 | Cross-sectional / relative-value lab (pairs, rotation, lead-lag) | KILL | 28 "survivors" were all SPY/IVV microstructure noise: 2.88 bps mean vs ~5 bps friction |
| 5 | Multi-asset regime signals (bonds-equity, gold, VIX risk-on/off) | no edge | no survivor after deflated Sharpe |
| 6 | Intraday QQQ strategies lab | DATA KILL | "Sharpe 11" came from put-call-parity-derived minute data, not real spot; lab disabled |
| 7 | PEAD (post-earnings announcement drift) | LOOK-AHEAD KILL | cohort defined by day-0 return while CAR included day 0; fixed CAR[+1,+21] = −3.70%, sign-flipped |
| 8 | 8-K item-type event study | no edge | no item category beat noise |
| 9 | QQQ options microstructure (spreads, depth, large quotes) | no edge | nothing actionable after costs |
| 10 | Small/illiquid universes (small-cap, REITs, BDCs, MLPs) | no edge | no survivor |
| 11 | Pre-2010 OOS extension on SPY strategies | no edge | candidates failed the extended window |
| 12 | IPO lock-up expiry | KILL | classic Field-Hanka effect fully decayed; CAR insignificant |
| 13 | CEF activist follow (Saba 13D) | MARGINAL FAIL | real +1.44% (1m) but dies to frictions; median 6m ≈ 0; convex tail only |
| 14 | SPAC trust arbitrage | KILL | premium below T-bills |
| 15 | CEF discount tilt (broad) | bounded, uncapturable | +0.7–3.6%/yr, capacity-limited, 2-yr horizon |
| 16 | CEF survival backtest on real (Tiingo) data | KILL | +10.5% mean was outliers + sector drift + a 224% data glitch; median ≈ 0 |
| 17 | News catalog Phase 2 (1,512 events, 27 catalyst cohorts) | 4 ARTIFACTS + 1 candidate | pooled baseline +2.39%: mega-cap-beta drift, not catalysts; same-sign up/down cohorts were the smoking gun |
| 18 | product_news__up matched-control test | KILL | matched (ticker, year) baseline absorbed the entire +9.26% (net +0.14%, t=0.07, perm p=0.47); cohort was TSLA-23/48, 2020-24/48 |
| 19 | VRP daily iron condor, QQQ in-sample (signed pre-reg) | KILL | PRIMARY exp −$5.96/t=−0.55; worse at 2× slippage; IV-RV↔pnl Pearson=0.01 — thesis falsified at the mechanism level. Positive cells were no-stop exploratory variants, not claimable |

Supporting infrastructure audits along the way: the engine-correctness audit
(2026-06-06, six defects found in the condor engine, A1 fixed immediately) and
the ThetaData depth probe (2026-06-11: floor = 2020-01, vendor day-holes in
May–Jul 2022 1-min data).

## The artifact taxonomy

Every kill belongs to one of seven classes. Future claims get checked against
all seven.

1. **Look-ahead leakage** (PEAD). The event-defining information overlaps the
   measurement window. Defense: measurement starts strictly after everything
   that defines the cohort; audit the window arithmetic explicitly.
2. **Friction-scale noise** (SPY/IVV "28 survivors"). The signal is real in
   bps but smaller than round-trip cost. Defense: report expectancy AFTER
   friction; never rank or filter on pre-cost metrics.
3. **Data glitches** (Tiingo 224% CEF). One impossible row inflates the mean.
   Defense: median-vs-mean sanity check; winsorize and re-test; inspect top-5
   contributors of every positive result by hand.
4. **Derived/fake data** (intraday "Sharpe 11"). The series isn't what it
   claims to be (parity-derived spot, stale quotes). Defense: provenance check
   on every new series — who made it, from what, with what staleness.
5. **Pooled-baseline contamination** (Phase 2's 4 fake survivors). The cohort
   inherits the universe's drift. Defense: smoking-gun symmetry test (do up
   AND down cohorts drift the same sign?) + baseline subtraction.
6. **Composition effects** (product_news__up). The cohort clusters in
   high-drift (ticker, year) cells; a pooled baseline understates the right
   control. Defense: matched (ticker, year) controls + composition-matched
   permutation test.
7. **Classifier hindsight leak** (product_news confidence gradient). An LLM
   labeling historical events knows what happened next; its selections and
   confidence inherit the future. Defense: treat LLM-built cohorts as
   contaminated by construction; matched controls absorb most of it; check
   whether classifier confidence "predicts" returns (it shouldn't).

An 8th candidate class — **stop-cadence look-back bias** in exit logic (audit
A3) — was verified NOT present (Phase 1 engine audit, 2026-06-11): exit
decisions are causal, using only the mark at the decision snapshot. The
documented caveat is the converse: under a once-daily cadence, an intraday
stop breach that reverts before the decision time is not realized — reported
P&L assumes no intraday risk control between decision points. A pinning test
(`test_exit_decisions_are_causal_at_the_decision_timestamp`) locks both
semantics.

## The mandatory gate checklist

Any future claim of edge must pass ALL of these, in order, and the report must
show each step:

1. **Pre-registration** — hypothesis, cohort definition, windows, N
   arithmetic, and kill criteria written and committed BEFORE results exist.
2. **Friction realism** — commissions + slippage on every leg; expectancy
   after costs is the only ranked metric.
3. **Look-ahead audit** — explicit statement of what information defines the
   cohort and proof the measurement window starts after it.
4. **OOS sign stability** — early/late split, same sign, both halves N≥10.
5. **Pooled baseline** — cohort return minus universe baseline; up/down
   symmetry check.
6. **Matched-control permutation** — composition-matched (ticker, year)
   placebo cohorts; claim requires perm p < 0.05 AND net |t| ≥ 2.
7. **Too-good-to-be-true tripwire** — Sharpe > 3, win rate > 85%, or median
   far from mean auto-triggers a placebo run and a top-contributor inspection
   before the result may be written down anywhere.
8. **Data provenance** — every new series documents source, construction, and
   staleness before use.

## What the campaign was worth

- A backtest engine whose 2022 result lands at the theoretical 68% win rate
  for 16-delta condors — i.e., an engine that validates against first
  principles instead of flattering the strategy.
- A 1,512-event classified catalyst catalog with reproducible tooling.
- A falsification harness (pre-reg templates, OOS splits, deflated Sharpe,
  baseline + matched-control machinery) that caught seven distinct artifact
  classes — several of which the standard gate would have missed.
- A true, decision-grade negative result: stop mining daily-bar public data
  on liquid mega-caps. That conclusion now has 19 tests behind it — including
  the one hypothesis (VRP) that had a real economic mechanism going in, which
  failed both statistically AND at the mechanism check (IV-RV↔pnl ≈ 0).

## What remains open (brain/29)

- **VRP regime suite** (Phase 4): QQQ in-sample KILLED 2026-06-13 (test #19,
  mechanism null). SPY arm is a separately-registered trial pending backfill;
  prior now very low. The unconditioned daily-condor VRP harvest as specified
  is dead — any revisit needs a conditioned variant under a new pre-reg.
- **CEF resolution-selection** (Phase 5): the one signal-side lead not killed
  — capacity-limited, operationally annoying, possibly real.

Both get the full checklist. If both die, the campaign closes with the honest
posture from decision 35: index core, rare high-conviction defined-risk bets,
and a machine that kills bad ideas before they cost money.
