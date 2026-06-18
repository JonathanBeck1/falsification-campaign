# ThetaData historical depth probe (Phase 0)

Probed via local ThetaTerminal REST (port 25510). Binding check: **1-min NBBO**
(what the condor engine consumes), not EOD. Pass = ≥300 one-min rows and ≥80%
two-sided quotes. Script: `scripts/probe_thetadata_depth.py` + manual boundary
mapping (curl) for the 2022 anomaly.

## Regime probe results

| regime | root | EOD contracts | 1-min rows | % two-sided | error |
|---|---|---:|---:|---:|---|
| volmageddon 2018-02-06 | SPY | — | — | — | HTTP 471 insufficient permissions |
| volmageddon 2018-02-06 | QQQ | — | — | — | HTTP 471 insufficient permissions |
| covid crash 2020-03-16 | SPY | 558 | 391 | 96% | — |
| covid crash 2020-03-16 | QQQ | 248 | 391 | 96% | — |
| bear 2022-06-13 | SPY | 414 | 0 | — | HTTP 472 no data (day-level hole) |
| bear 2022-06-13 | QQQ | 336 | 0 | — | HTTP 472 no data (day-level hole) |
| control 2026-05-15 | SPY | 528 | 391 | 100% | — |
| control 2026-05-15 | QQQ | 532 | 391 | 100% | — |

## Boundary mapping (SPY, 1-min quotes)

- **2019-06-03: PERMISSION DENIED** → subscription floor is 2020. 2018
  volmageddon is out of tier entirely (both EOD and 1-min denied).
- 2020-06, 2021-06, 2023-06, 2024-06, 2025-06: ✅ both EOD and 1-min serve.
- **2022: EOD serves everywhere, but 1-min has scattered DAY-LEVEL holes**
  concentrated in May–July:
  - missing: 05-16, 06-10, 06-13, 06-14, 06-17, 07-05
  - present: 01-14, 03-15, 04-18, 05-02, 06-01, 06-15, 06-16, 07-18, 08-01,
    08-15, 10-17, 12-15
  - QQQ fails the SAME dates as SPY → vendor-side data gaps, not contract,
    strike, or transient issues (failures reproduced on retry, multiple
    expirations and strikes per date).

## Verdict

- **Usable 1-min window: 2020-01 → present (6+ years).** Includes the COVID
  crash (full fidelity) and the 2022 bear (with holes).
- **Volmageddon 2018 is unavailable** at this tier. Phase 4 either drops that
  regime or pays for a tier/vendor upgrade — decide only if 2020+2022 results
  warrant it.
- **2022 requires a coverage scan before backfill**: loop all 2022 trading
  days probing one ATM contract each, produce the exact missing-day list, and
  the backfill ledger must mark those days MISSING_VENDOR (not retry-forever).
  Ironically the holes cluster exactly at the June 2022 bear low — per-regime
  expectancy for 2022 must report coverage % alongside results.

## Phase 4 consequences (brain/25 amendments needed)

1. OOS window = 2020–2025, not 2018–2025. Redo N arithmetic on 6 years.
2. Regime cuts available: COVID crash ✅, 2021 calm ✅, 2022 bear ⚠️ partial,
   2023–2025 ✅. No volmageddon.
3. Backfill design: day-level coverage ledger with MISSING_VENDOR state;
   coverage % is a mandatory column in every per-regime result table.
