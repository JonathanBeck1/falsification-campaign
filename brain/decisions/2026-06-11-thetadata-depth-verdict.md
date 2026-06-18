# Decision: ThetaData depth verdict — VRP suite runs 2020–2025, volmageddon out

Date: 2026-06-11
Status: Phase 0 of brain/29 complete. Phase 4 is UNBLOCKED with a revised window.

## What we verified (it was an unverified assumption until today)

brain/25's options OOS protocol silently assumed historical 1-min option
quotes existed for 2018, 2020, and 2022. Probed the local ThetaTerminal REST
API directly (`scripts/probe_thetadata_depth.py` +
`research/thetadata_depth_probe.md`).

## Findings

1. **Subscription floor is 2020-01.** 2018 and 2019 return HTTP 471
   (insufficient permissions) for both EOD and 1-min. The volmageddon regime
   is unavailable without a tier/vendor upgrade.
2. **2020-03-16 (COVID crash) serves full 1-min NBBO** — 391 rows, 96%
   two-sided, 558 SPY contracts on the chain. The single most valuable stress
   date is fully covered.
3. **2022 has vendor-side day-level holes in 1-min data** (EOD is fine),
   clustered May–July 2022: 05-16, 06-10, 06-13, 06-14, 06-17, 07-05
   confirmed missing; SPY and QQQ fail identical dates, reproducible across
   strikes and expirations. The holes sit exactly at the June 2022 bear low.
4. 2021, 2023, 2024, 2025, 2026 all serve cleanly (control date 100%
   two-sided).

## Decision

- **Phase 4 window: 2020-01 → 2025-12 (6 years).** Regimes: COVID crash
  (full), 2021 calm, 2022 bear (partial), 2023–25 chop/bull.
- **Do NOT buy a tier upgrade now.** Volmageddon coverage only becomes worth
  paying for if the 2020+2022 results are promising enough to need a third
  crash regime as confirmation.
- **Backfill prerequisite: a full-year 2022 coverage scan** (one ATM contract
  per trading day) to enumerate every missing day BEFORE the chain backfill.
  Ledger gets a MISSING_VENDOR state so the backfill doesn't retry forever.
- **Coverage % is a mandatory column** in every per-regime result table —
  a 2022 expectancy claim that silently omits the bear low would be artifact
  class #7 (selection via data availability).
- brain/25 N arithmetic must be redone on the 6-year window and signed before
  any backtest runs (carried into Phase 4 pre-registration).

## AMENDMENT (same day): full-window day-level scan results

The follow-up two-pass scan of all 1,507 trading days 2020-2025
(`research/coverage_1min_2020_2025.md`) supersedes the "holes clustered
May-Jul 2022" estimate. Reality:

- 2020, 2023, 2024, 2025: **100% day-level 1-min coverage.**
- **2021: 69.4%. 2022 (through Aug 19): 67.3%.** All 159 missing days fall in
  the 2021-01 -> 2022-08 span; ~38% of that span is dark at the Value tier.
- v3 endpoint not exposed by our terminal; tick-level blocked on Value tier.

Phase 4 design updates: engine must handle positions crossing missing days
(carry-last-mark + flag), per-regime coverage % is mandatory, and the
2021/2022 cohorts are pre-declared DEGRADED. The COVID-crash and 2023-2025
regimes carry the evidentiary weight; 2022-bear results are supporting-only.
