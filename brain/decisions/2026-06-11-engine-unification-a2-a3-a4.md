# Decision: Condor engines unified (A2), A3 cleared, sweeps re-ranked (A4)

Date: 2026-06-11
Status: Phase 1 of brain/29 complete. The audit's remaining engine items are
closed. Full suite: 1,231 passed, 0 failed; ruff clean repo-wide.

## A2 — one marking core, two engines

The EOD path (`src/trader/options/backtest.py`) had FIVE divergences from the
fixed intraday path: no wing cap (stale deep-ITM quotes could book losses
exceeding max_risk), no intrinsic floor (breaches hidden behind stale quotes
booked fake profit-target wins), no intrinsic settlement at expiration, zero
friction with no config knobs, and a dead expiration branch (`dte <= 0`
checked after `dte <= exit_dte`, so "expiration" was unreachable).

Deletion wasn't appropriate — the EOD path has live CLI users
(`options-backtest-iron-condor`, `options-sweep-iron-condor`). Instead both
engines now price every close through ONE shared core,
`mark_condor_close_debit()` (`src/trader/options/iron_condor.py`): bounded
debit (intrinsic floor, wing cap), expiration-only intrinsic settlement,
exit slippage on 4 legs capped at the wing. The intraday change is a pure
extraction refactor — verified bit-identical on a replay of the reference
no-stop config (gate window 2022-01-03..07: before/after reports byte-equal;
opened trade matches reference trade #1 in the trades-repo 2022 report,
strikes 365/370/422/427, credit 0.72). The EOD path's numbers change BY
DESIGN; the new EOD tests quantify each fix. A parametrized engine-parity
test asserts both engines produce identical credit/debit/pnl/exit-reason for
identical inputs, frictionless and with friction.

## A3 — verdict: NO look-back violation

Exit decisions are causal: under the 15:55 cadence the decision uses only the
mark at the first snapshot ≥ 15:55; under every-minute cadence stops fill at
the first breach minute at that minute's debit. The genuine caveat is the
converse direction: a mid-day breach that reverts before the decision time is
not realized (visible only in max_adverse_pnl) — reported P&L under daily
cadence assumes no intraday risk control between decision points. Documented
in the config and pinned by
`test_exit_decisions_are_causal_at_the_decision_timestamp`.
The provisional "8th artifact class" in brain/30 is resolved as NOT PRESENT.

## A4 — sweeps rank on expectancy t-stat, not win rate

EOD sweep ranked by `(total_pnl, win_rate, -max_drawdown)` — the win-rate
trap. Both sweeps now rank by after-friction per-trade expectancy t-stat →
expectancy → trade count, with zero-trade rows sunk last (this also fixed the
one pre-existing test failure on the branch). Win rate remains a reported
column only. A test demonstrates a config that wins on BOTH win rate and
total P&L being correctly dethroned.

## Honest scope of the sanity gate

trader-catalyst has no local option data; the full-2022 replay lives in the
trades repo (202 GB SQLite, read-only access only — Store init was bypassed
because it runs migrations). At ~14 min/day of I/O a full-year before/after
was infeasible; the gate window was one week, byte-identical. The full-year
re-validation rides on the next real backtest run (Phase 4), which uses this
engine.

## Consequence

Phase 4 (VRP regime suite) is now UNBLOCKED on both gates: data depth
(2026-06-11 depth verdict) and engine correctness (this doc). Next: amend +
sign brain/25 (pre-registration on the 2020–2025 window with the coverage
ledger), then backfill.
