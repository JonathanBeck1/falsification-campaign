# Options Engine Correctness Audit — Findings & Prioritized Actions

Author: the maintainer (via Claude Code) · Date: 2026-06-06 · Branch: `claude/engine-correctness-audit`

## Decision

Before any iron-condor edge number is trusted, the backtest engine and the
research protocol have gaps that will distort the verdict. This is a read-only
audit record: it authorizes no live trading and signs no protocol. Each finding
below was reproduced against `main` (post-#101/#103) or cites file:line. Items
are ordered by how much they can distort the headline edge or block the OOS run.

The first item is already fixed in a separate PR; the rest are proposed work,
each scoped to be an independent, cherry-pickable change.

---

## A. Confirmed engine defects

### A1 — Missing-leg fake-win (FIXED in PR #104). Severity: high.
`bounded_close_debit` settles an open OTM condor to its zero intrinsic when the
four leg quotes are momentarily missing, booking a fabricated max-profit
`profit_target` win. Intrinsic settlement is only valid at expiration. Repro on
`main`: a mid-life leg gap over an OTM underlying closes as a **+$130 win**.
Fix gates the fallback on `dte <= 0`. See PR #104 (`claude/engine-realism-fix`).

### A2 — EOD `backtest.py` retains every original defect. Severity: high.
`src/trader/options/backtest.py` was **not** touched by #101. It imports the raw
`close_debit` (not `bounded_close_debit`), so it has **no defined-risk cap, no
intrinsic settlement, and no transaction costs**, and it still contains the dead
expiration-ordering branch. A headline number sourced from the EOD path would be
untrustworthy in exactly the ways #101 fixed for intraday.
**Action:** route EOD marking through `bounded_close_debit` + a cost model (with
the A1 `dte` fix), or deprecate `backtest.py` and assert in CI that no headline
result comes from it. Mirror #101's marking tests for the EOD path.

### A3 — Once-a-day (>=15:55) stop/profit cadence is look-back-favorable. Severity: high.
`exit_decision_time` defers profit-target/stop exits to the first snapshot at/
after the cadence time. A 2x-credit stop breached at 11:00 is **not realized** if
the underlying reverts by 15:55 — the breach survives only as reporting-only
`max_adverse_pnl`, never as a `stop_loss` exit. For a short-vol edge-proof this
systematically flatters tail behavior on the Feb-2018/Mar-2020/2022 reversal days
that decide pass/fail.
**Action:** either evaluate the stop every minute and fill at first breach, or
explicitly document that reported PnL assumes **no intraday risk control** and
size accordingly. Add a test: a midday MAE breach with a benign 15:55 mark must
realize a `stop_loss` exit at the breach.

### A4 — Sweep ranks on win-rate / total-PnL, not expectancy. Severity: medium.
`options/sweep.py` and `options/intraday_sweep.py` rank configurations by
`total_pnl` then `win_rate` — the exact win-rate trap `brain/27 §4` warns against.
An overfit, high-win-rate, **negative-expectancy** condor tops the sweep today.
**Action:** make per-trade **expectancy** (and its t-stat) the primary sort key;
the deflated-Sharpe machinery already exists (`scoring/deflated_sharpe.py`) but is
wired only to the deprecated equity leaderboard.

---

## B. Engineering health

### B1 — No CI. Severity: high (leverage).
There are no `.github/workflows/`; the ~1000-test suite and ruff run nowhere
automatically, so a PR can merge red. Today `main` already ships **10 pre-existing
`RUF002`** errors in `scoring/deflated_sharpe.py` (ambiguous Greek letters in the
math docstring) that a lint gate would have caught.
**Action:** add `ci.yml` running `ruff check`, `ruff format --check`, and
`pytest`, required on PRs. Fix or `allowed-confusables`-exempt the deflated-Sharpe
docstring so `main` is green on day one.

### B2 — Tests validate the frictionless engine; the realistic path is thin. Severity: medium.
Friction defaults are neutral (0) at the library level and realistic only on the
CLI, so most unit tests exercise the frictionless engine. There are no behavioral
**financial invariants**.
**Action:** add property tests asserting, for every closed trade:
`-max_risk*mult - costs <= pnl <= entry_credit*mult`; close debit <= wing;
deep-ITM-at-expiry settles to exact max-loss; and a cost-aware end-to-end test
where a thin-credit winner flips to a loser after costs.

### B3 — Make the invariants un-bypassable (structural). Severity: medium.
The intraday and EOD engines are divergent reimplementations of marking/
settlement — the root cause of the A1/A2 class of bugs. **Action:** extract one
shared, property-tested marking/settlement core used by both paths.

---

## C. Data & protocol blockers

### C1 — ThetaData Value history depth is unconfirmed (the #1 blocker). Severity: critical.
The regime-coverage rule requires the selection window to include Feb-2018,
Mar-2020, and 2022. Nothing in the repo confirms Value serves data before ~2024;
only a 5-day 2026 smoke sample exists. If Value can't reach 2018 the OOS milestone
needs a different vendor/tier — and we'd learn this only after engineering a
multi-hour backfill.
**Action:** run a 3-date depth probe (one trading day each in Feb-2018, Mar-2020,
2022) for SPY via the existing ThetaData adapter and record rows-or-
PERMISSION_DENIED in a decision doc **before** building the full backfill.
Pre-price a Polygon/ORATS fallback so a "no" is one decision, not a re-architecture.

### C2 — N>=30-in-OOS vs a 90-day OOS window is arithmetically inconsistent. Severity: high.
At ~12 non-overlapping 40-DTE trades/year, a 90-day OOS yields ~3 trades; N>=30
needs ~2.5 years of OOS, which forces a >=7-8 year regime-complete backfill. Pick
window / N / cadence (or switch to a block-bootstrap CI / sign test on per-trade
P&L) and write it into the locked `brain/25` **before** seeing data — changing it
after is p-hacking under the protocol's own rules.

### C3 — `brain/26` merged to `main` unsigned and equity-scoped. Severity: high (governance).
`brain/26` is on `main` (via #93) still containing `<<<FILL IN>>>` placeholders,
still equity-era in scope, and its own "no PR merges until the pre-registration
is countersigned" hard rule is both violated (PRs keep merging) and unsatisfiable
as written. There is **no committed options threshold set**, so no OOS "pass" can be
declared legitimately.
**Action:** fill `brain/26` with the options hypothesis + thresholds from
`brain/27 §3-4` and countersign, OR explicitly scope the §6 hard rule to
live-trading / strategy-selecting PRs and exempt research-infra PRs.

---

## D. Collaboration

### D1 — Recover the unique work from the closed #97/#98 stack. Severity: medium.
PRs #97/#98 were closed (not merged). Their genuinely-unique pieces are **not on
`main`**: forward-implied delta primitives (`greeks.py`), the early-assignment
detector (`assignment.py`), and the proposed `options-validate-data` CLI.
**Action:** reconstruct these as a fresh PR off current `main`, **renumbering the
assignment migration to m0009** (re-using m0008 would silently no-op against
`main`'s existing m0008 ledger and the columns would never be created).

### D2 — Branch-lane deconfliction. Severity: low.
The `#98`/`#101` cost-model collision happened because the same fix was built
twice in parallel branches. **Action:** per-lane namespacing (e.g.
`claude/<topic>/*`) and a "`git fetch && gh pr list` before touching shared
options files" habit.

---

## Suggested sequence

1. Land PR #104 (A1) — gates trustworthiness of every intraday number.
2. C1 depth probe (30-60 min) — decides whether the whole plan is feasible.
3. B1 CI — stop shipping red.
4. C3 + C2 — lock a signable, internally-consistent protocol before any OOS run.
5. A2/A3/A4 + B2/B3 — make the engine and selection metric trustworthy.
6. D1 — recover forward-delta + assignment.

## Validation

This is a docs-only change. `ruff` / `pytest` unaffected.
