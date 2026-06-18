# Brain 29 — Build Plan: Close the Campaign End-to-End

Date: 2026-06-11
Owner: the maintainer + Claude (Fable 5)
Status: ACTIVE

## Context

18 pre-registered tests, 18 kills (see decisions through 2026-06-10). Daily-bar
public-data anomalies on liquid mega-caps are a settled null. Two hypothesis
classes remain with non-trivial priors: (a) volatility risk premium harvested
with the now-honest condor engine, (b) CEF resolution-selection (the one
"real but uncapturable broadly" finding). Everything else below is either a
blocker for those two tests or hardening that prevents the 19th artifact.

End state: both remaining hypotheses get a decisive verdict from the same
falsification machine. Then the strategic fork (deploy paper discipline vs.
crystallize as platform + proven negative result) gets decided on evidence.

## Phase 0 — ThetaData historical depth probe  ⛔ GATES PHASE 4

> **DONE 2026-06-11** — verdict: floor is 2020-01 (volmageddon out); COVID
> crash fully covered; 2022 has vendor-side day-level 1-min holes (May–Jul).
> Phase 4 window revised to 2020–2025. See
> `decisions/2026-06-11-thetadata-depth-verdict.md`.

**Question:** does our ThetaData subscription serve option quotes deep enough
to cover Feb-2018 (volmageddon), Mar-2020 (COVID crash), and 2022 (bear)?
brain/25's OOS protocol silently assumes yes; nobody has verified.

- Probe via local ThetaTerminal REST (port 25510): EOD + 1-min NBBO quotes for
  ATM SPY/QQQ contracts on 2018-02-06, 2020-03-16, 2022-06-13, plus a recent
  control date.
- Outcomes:
  - **Full depth** → Phase 4 runs 2018–2025 as designed.
  - **Partial** (e.g. 2020+) → Phase 4 OOS plan shrinks; re-do N arithmetic
    in brain/25 BEFORE running anything.
  - **None / 1yr only** → Phase 4 blocked on vendor decision (document cost
    options; no engineering until decided).
- Deliverables: `scripts/probe_thetadata_depth.py`,
  `research/thetadata_depth_probe.md`, decision doc.
- Effort: hours.

## Phase 1 — Condor engine unification (audit A2/A3/A4)

**Why:** the intraday path carries the bounded-debit + intrinsic-settlement
fixes; the EOD path (`src/trader/options/backtest.py`) does not. Two marking
implementations = the next fake result waiting to happen.

- A2: extract ONE marking/settlement function; both paths call it — or delete
  the EOD path outright if Phase 4 only needs intraday. Decide by usage.
- A3: stop-cadence look-back bias — exits must use only information available
  at the decision timestamp.
- A4: sweep ranking on expectancy (mean P&L after friction), never win-rate.
- Tests: marking-parity test between paths; re-run the 2022 no-stop sanity
  gate — the −$42 / 68%-win result must reproduce.
- Effort: 1–2 days. Independent of Phase 0; can run in parallel.

## Phase 2 — CI (ruff + pytest on every PR)

- GitHub Actions: `ruff check` + `pytest -m "not integration"` on PR + push.
- Fix existing ruff errors so it starts green (main currently ships RUF002s).
- Spawned as a separate one-click task (task chip, 2026-06-10). Trades repo
  gets the same workflow after trader-catalyst proves it.
- Effort: half a day.

## Phase 3 — Campaign retrospective (the durable artifact)

- `brain/30_campaign_findings.md`: all 18 tests, one paragraph each — what was
  tested, how it died, which artifact class killed it.
- Artifact taxonomy: look-ahead (PEAD), friction-scale noise (SPY/IVV), data
  glitches (Tiingo 224%), derived-not-real data (intraday lab), pooled-baseline
  contamination (Phase 2), composition effects + LLM hindsight leak
  (product_news matched-control kill).
- Codify the mandatory gate checklist for ANY future survivor claim:
  pre-registration → friction realism → look-ahead audit → OOS sign stability
  → pooled baseline → **matched-control permutation** → too-good-to-be-true
  tripwire (Sharpe > 3 or win > 85% auto-flags a placebo run).
- Stretch: implement the checklist as a shared report module so studies can't
  skip gates silently.
- Effort: 1 day. No dependencies.

> **CLOSED 2026-06-13** — QQQ in-sample KILL (PRIMARY exp −$5.96/t=−0.55;
> mechanism IV-RV↔pnl Pearson=0.01). VRP track closed; SPY not run; OOS
> pristine. See decisions/2026-06-13-vrp-track-closed.md.

## Phase 4 — VRP regime suite  (contingent on Phase 0 + Phase 1)

The one options hypothesis with a real economic mechanism (structural
overpayment for insurance) tested on the honest engine across regimes.

- **Pre-register FIRST** (amend brain/25, sign it): strategy grid (short
  condor / strangle / put at fixed deltas), entry/exit rules, friction model,
  N arithmetic, OOS split, kill criteria. Locked before any backfill completes.
- Backfill SPY + QQQ chains for whatever depth Phase 0 confirmed (rate-limited,
  resumable — backfill.py already does this).
- Run walk-forward + deflated Sharpe; regime cuts: 2018 volmageddon, 2020
  crash, 2022 bear, calm years. Report per-regime expectancy after friction.
- Verdict is binary and final for the options track: deployable paper
  candidate, or the track closes with a decision doc.
- Effort: backfill is days of wall-clock (rate limits); analysis ~2 days.

## Phase 5 — CEF resolution-selection study

The only signal-side lead the machine didn't kill (decisions 32/34/35/36):
broad CEF discount tilt is worthless, but the convex tail (activist-targeted /
terminating funds) might be selectable.

- **Hard part first: survivorship-bias-free universe.** Delisted/merged CEF
  price history. Options: Tiingo + manually-built delisting list from SEC
  filings; Sharadar; or accept a documented bias bound. Decide and document
  before any return is computed.
- Selection signal: 13D/13G filings on CEFs (EDGAR plumbing exists), fund
  termination/tender announcements from N-CSR/497 filings.
- Pre-register: cohort = CEFs entering activist/termination state; control =
  matched discount-decile CEFs without the state; CAR on NAV-discount close,
  not just price. Full gate checklist from Phase 3 applies.
- Capacity reality stated up front: this is personal-account-scale at best.
- Effort: the largest item — 1–2 weeks elapsed. Independent of Phases 0/1/4.

## Sequencing

```
Phase 0 (hours) ──┬──> Phase 4 (pre-reg -> backfill -> verdict)
Phase 1 (1-2d) ───┘
Phase 2 (0.5d, parallel, chip queued)
Phase 3 (1d, parallel)
Phase 5 (1-2wk, parallel after Phase 3 checklist exists)
```

After Phases 4 + 5 deliver verdicts: fork decision (paper deployment vs.
platform crystallization) gets its own brain doc.

## Rules of engagement (unchanged)

Research-only, no live trading. Every phase ends in a decision doc. Every
survivor claim runs the full gate checklist. Work on `claude/*` branches;
the maintainer merges.
