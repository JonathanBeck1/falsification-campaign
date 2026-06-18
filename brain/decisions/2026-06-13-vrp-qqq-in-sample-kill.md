# Decision: VRP primary FALSIFIED in-sample on QQQ — mechanism null is the deep finding

Date: 2026-06-13
Status: Phase 4 (brain/29) — QQQ arm complete. PRIMARY hypothesis dead in-sample.
The OOS window (2023–2025) was NOT touched and remains pristine.
Report: trades-repo `research/vrp/IS_QQQ_2020-01-02_2022-12-31.{md,json}`.

## What ran

The signed brain/31 grid (8 cells) on QQQ in-sample 2020-01-02 → 2022-12-31,
756/782 weekdays populated (96.7%), honest unified engine, full friction.

## Result — PRIMARY cell (16Δ, PT 50%, 2× stop)

| metric | value | gate |
|---|---:|---|
| expectancy / trade | **−$5.96** | gate 1 FAIL (need > 0) |
| t-stat | −0.55 | gate 1 FAIL (need ≥ 2) |
| N | 99 | ok |
| expectancy @ 2× slippage | −$24.59 (t=−2.41) | gate 3 FAIL |
| Pearson(IV-RV spread, pnl) | **0.01** | gate 4 "PASS" by sign, but ~0 |

Gate 1 and gate 3 fail. Per brain/31 kill criteria, QQQ's VRP claim is dead.

## The deep finding: the mechanism is null

gate 4's correlation between entry-day IV–RV spread and per-trade P&L is
**0.01** — zero. The quartile table is flat (Q1 −$7.16 → Q4 −$0.92, no
monotonic gradient). The strategy's returns, such as they are, are NOT a
function of how overpriced vol is at entry. This is the volatility-risk-premium
thesis falsified at the mechanism level — and that conclusion is
underlying-agnostic. The +0.01 nominally clears gate 4's "> 0" sign bar, which
is itself a lesson: a sign-only mechanism gate is too weak; future
pre-registrations should require a minimum |correlation| or a monotone
quartile gradient.

## The secondary cells are NOT a result (discipline note)

Three secondary cells are positive: d16_ptnone_stopnone (+$28.39, t=2.38),
d25_ptnone_stopnone (+$41.61, t=2.03), d16_pt50_stopnone (+$18.30, t=1.68).
brain/31 §4 tags all 7 secondary cells exploratory and forbids claiming edge
from this run; any follow-up needs a NEW pre-registration on fresh (2026+)
data. Two cells at t≈2 across 14 exploratory trials (7 cells × 2 underlyings)
is expected under the null. Moreover every positive cell is a **no-stop**
variant — the documented condor failure-mode reversal (stops realize whipsaw
losses; removing them defers loss recognition and fattens the left tail; see
trades-repo `research/qqq_regime_findings.md`), and the null mechanism check
says none of it is VRP. We do NOT carry any secondary cell to OOS.

## Engine sanity (the kill is real, not a bug)

d25_pt50_stop2x lost −$69.98/trade (t=−4.05, 36% win) — 25Δ shorts sit near
the money, get breached often, and the 2× stop realizes those losses. The
engine correctly produces a large, significant NEGATIVE where theory predicts
one; it is telling the truth, not malfunctioning. N=99 over 3y (~33/yr) is
consistent with PT/stop-driven re-entry.

## What this is

Test #19 of the campaign, and a clean kill: pre-registered, mechanism-
confirmed, OOS untouched. This is precisely the outcome the apparatus was
built to deliver — a tempting headline (three "winning" cells) refused on
principle, and the actual hypothesis falsified both statistically and
mechanistically.

## Open decision: run SPY or close the track?

brain/31 registered SPY as a separate trial; its backfill is ~1,124 days from
done. The null mechanism check is underlying-agnostic, so the prior on SPY is
now very low. Options recorded for Jonathan:
- (A) Run SPY anyway to honor the 2-trial pre-registration as written
  (confirmation, not hope) — costs days of backfill + hours of compute.
- (B) Close the VRP track now on the QQQ kill + mechanism null, document SPY
  as not-run, and move to Phase 5 (CEF, brain/32).
Either way, the unconditioned daily-condor VRP harvest as specified is dead;
any future options work must be a conditioned variant under a new
pre-registration.
