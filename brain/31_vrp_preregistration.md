# Brain 31 — VRP Regime Suite: Pre-Registration (Phase 4 of brain/29)

Date: 2026-06-12
Status: **AWAITING SIGNATURE.** No backtest may produce a number on the
2020–2025 option data until the maintainer signs the block at the bottom. Data
backfill MAY proceed before signature (acquisition cannot bias selection);
engine runs may not.

Lineage: brain/24 (gate criteria), brain/27 (VRP strategic frame), brain/29
(build plan), brain/30 (artifact taxonomy + checklist),
decisions/2026-06-11-thetadata-depth-verdict.md (data reality),
decisions/2026-06-11-engine-unification-a2-a3-a4.md (engine correctness).

## 1. Hypothesis

Implied volatility on SPY/QQQ structurally exceeds realized volatility
(volatility risk premium). A disciplined, defined-risk short-vol program —
iron condors sold at fixed delta, managed mechanically — captures a positive
after-friction per-trade expectancy that survives out-of-sample evaluation
and is not an artifact of any class in brain/30's taxonomy.

Falsifiable prediction: the PRIMARY configuration (below) shows OOS
(2023–2025) after-friction expectancy > 0 with t ≥ 2 on N ≥ 30 trades per
underlying, same sign as in-sample.

## 2. Data (locked)

- Source: ThetaData 1-min NBBO via local ThetaTerminal; engine = the unified
  intraday path (`mark_condor_close_debit` core).
- Underlyings: SPY and QQQ. Window: 2020-01-02 → 2025-12-31.
- Coverage (corrected 2026-06-12 by lake inventory — supersedes the
  vendor-only ledger):
  - **QQQ: 100% — every trading day 2020–2025 already resides in the local
    lake** (trades-repo `option_quote_bars_1m`, backfilled before the vendor's
    2021–22 data went dark; spot-verified 371k–554k rows/day on days the
    vendor now returns nothing). The degraded-regime declaration does NOT
    apply to QQQ.
  - **SPY: 2020 + ~half of 2021 in the lake; ~1,124 days to backfill.** For
    Jan 2021–Aug 2022 the vendor is missing ~38% of days
    (`research/coverage_1min_2020_2025.md`), so SPY 2021–2022 IS pre-declared
    DEGRADED. SPY's availability check (gate 5) is correspondingly binding.
  - QQQ is therefore the higher-evidence underlying by construction; this is
    declared now, before any result exists.
- Missing-day handling (locked): no entries on MISSING_VENDOR days; positions
  open across them carry the last mark and the trade is flagged
  `crossed_gap`. Per-regime tables MUST report day-coverage % and the count
  of gap-crossing trades.

## 3. In-sample / out-of-sample split (locked)

- **In-sample (selection): 2020-01 → 2022-12.** Contains the COVID crash and
  the (degraded) 2022 bear. All parameter inspection happens here.
- **Out-of-sample (one shot): 2023-01 → 2025-12.** 100% data coverage.
  Evaluated ONCE, after IS analysis is written down and committed. No
  parameter may change after the first OOS run; there is no second shot.

## 4. Strategy grid and multiple-testing accounting (locked)

Common mechanics (all configs): entry daily at 09:45 ET when no position is
open (max 1 concurrent per underlying); 30–45 DTE expiration; $5 wings;
exit decisions once daily at 15:55 ET; time exit at DTE ≤ 21; reject
degenerate entries per engine rules.

**PRIMARY (the hypothesis — one per underlying):**
- Iron condor, 16Δ shorts, profit target 50% of credit, stop at 2× credit.

**SECONDARY (exploratory; reported, but CANNOT claim edge from this run):**
- short delta ∈ {16, 25} × profit target ∈ {50%, none} × stop ∈ {2×, none},
  minus the primary cell = 7 configs per underlying.

Trial accounting: 2 primary trials (SPY, QQQ) judged at t ≥ 2. The 14
secondary cells are exploratory by construction; any interesting secondary
result requires a NEW pre-registration and fresh data (2026+) to be claimed.
This is the brain/30 defense against the deflated-Sharpe trap: the primary
hypothesis count is two, not sixteen.

## 5. Friction (locked)

- Commission $0.65/contract × 4 legs × 2 sides = $5.20/trade.
- Slippage $0.02/contract/leg at entry and exit (exit baked into mark).
- Sensitivity gate: the primary result must keep expectancy > 0 at 2×
  slippage ($0.04). If it dies at 2×, it is "marginal," not "edge."

## 6. N arithmetic (locked)

Holding period 9–24 days with max 1 concurrent → ~15–25 trades/yr/underlying.
Expected N: in-sample ≈ 45–75 (less in degraded years — that loss is priced
in here, before results exist), OOS ≈ 45–75 with full coverage. Both splits
clear the N ≥ 30 bar from brain/24. If realized OOS N < 30, the verdict is
"insufficient sample," not pass or fail.

## 7. Gates and kill criteria (locked — the brain/30 checklist applied)

The primary config, per underlying, must pass ALL of:
1. OOS after-friction expectancy > 0, t ≥ 2, N ≥ 30.
2. IS and OOS expectancy same sign.
3. Survives 2× slippage sensitivity.
4. **Mechanism check:** per-trade P&L correlates positively with
   entry-time IV–RV spread (VIX/realized-vol proxy acceptable). VRP edge
   must come from when vol is overpriced; an "edge" uncorrelated with the
   premium it claims to harvest is an artifact.
5. **Availability check:** expectancy in full-coverage periods alone
   (2020, 2023–2025) must independently satisfy gate 1. Profit concentrated
   in degraded periods = selection-via-availability artifact.
6. Too-good tripwire: Sharpe > 3 or win rate > 85% or |median − mean| large
   → mandatory placebo run + top-5 trade inspection before anything is
   written down.

Kill: if either underlying's primary fails the gates, that underlying's VRP
claim is dead. If BOTH fail, the options track closes per brain/27 Outcome B
with a final decision doc. Secondary cells cannot rescue the verdict.

## 8. Execution order

1. The maintainer signs below.
2. Lake inventory vs vendor availability → backfill delta plan (SPY full,
   QQQ gaps), resumable ledger with MISSING_VENDOR states.
3. Backfill runs (days of wall-clock; rate-limited).
4. IS run → IS report committed BEFORE any OOS execution.
5. Single OOS run → final report → decision doc, whatever the answer.

## 9. Signature

By signing, the maintainer affirms: the hypothesis, grid, split, friction, N
arithmetic, and kill criteria above are final; the OOS window will be
evaluated exactly once; a kill verdict will be published with the same
prominence as a pass.

- [x] **Signed: the maintainer  date: 2026-06-12** (confirmed in-session; grid,
  split, friction, and kill criteria locked as written above)

## Addendum — operationalizations (recorded 2026-06-12, BEFORE any IS run)

The runner (`trades` repo, `scripts/run_vrp_suite.py`) required four
operationalizations of under-specified points. None changes a locked
parameter; all were fixed before the first result existed:

1. Tripwire "|median − mean| large" → gap > 1 per-trade standard deviation.
   Sharpe (undefined above) → annualized per-trade: (mean/sd)·√(trades/yr).
2. Gap-crossing trade = closed trade whose [entry, exit] interval contains a
   weekday with zero quote rows. Market holidays inflate the count slightly —
   conservative direction (can flag extra, can never hide a vendor gap).
3. "None" PT/stop cells use unreachable engine sentinels (PT 1000%,
   stop 1e9×) — provably inert given debit ∈ [0, wing].
4. Gates 2 and 5 (IS/OOS sign stability, availability split) are cross-run by
   definition; the per-run report says so explicitly rather than evaluating a
   degenerate version.

Known engine property (pre-existing, not a change): 16Δ selection uses
Black-Scholes deltas estimated from quote mids — no point-in-time Greeks
exist at this data tier. This is the same engine the trusted 2022 result
validated at the theoretical 68% win rate.
