# Decision: VRP options track CLOSED — pivot to Phase 5 (CEF)

Date: 2026-06-13
Status: brain/29 Phase 4 closed. Decision by Jonathan in-session.

## What was decided

After the QQQ in-sample kill (decisions/2026-06-13-vrp-qqq-in-sample-kill.md:
PRIMARY exp −$5.96/t=−0.55, mechanism IV-RV↔pnl Pearson=0.01), the
unconditioned daily-iron-condor VRP harvest as specified in brain/31 is
declared DEAD. SPY was a separately-registered trial but the mechanism null is
underlying-agnostic, so its prior is now very low and the ~1,124-day backfill
is not worth the Mac-mini time for a near-certain confirmation.

- SPY arm: **NOT RUN.** Backfill paused (resumable from ledger if ever needed).
- The 2023–2025 OOS option data remains **pristine and unused** — available
  for any FUTURE conditioned-variant pre-registration, should one ever be
  written.
- QQQ 2020–2025 lake (`trades/lake/`, 4.1 GB, 1,508 partitions) is retained;
  the 2021–2022 portion is irreplaceable (vendor no longer serves it) — the
  offsite-backup task remains open.

## Why this is the right close (not premature)

The VRP hypothesis was the project's single best options-side idea — the one
with a documented economic mechanism (structural overpayment for insurance).
It failed on the honest engine both statistically AND at the mechanism level.
A sign-only mechanism gate let +0.01 nominally "pass," but the quartile table
was flat: returns do not depend on how overpriced vol is at entry. There is no
VRP being harvested here. Running SPY to reconfirm would be diligence theater.

## Methodology upgrade carried forward

Future pre-registrations must use a STRENGTHENED mechanism gate: a minimum
|correlation| (e.g. ≥ 0.15) or a monotone quartile gradient in the
hypothesized driver — not merely "correlation > 0". Added to the brain/30
checklist intent.

## Next: Phase 5 (CEF resolution-selection, brain/32)

The only signal-side lead the campaign never killed. Data plan adopted in
brain/32 (Tiingo NMFQS NAV symbols give survivorship-free daily NAV incl.
delisted funds; SEC series/class CSVs as identity spine; EDGAR EFTS events).
Tiingo key confirmed present on disk. Existing infra is richer than the memo
assumed: src/trader/catalysts/ already has cef_events.py, cef_resolution.py
(unit-tested), cef_study.py, tiingo.py, prices.py.

Phase 5 build order (free groundwork first, no spend):
1. Universe spine — SEC investment-company series/class CSVs 2015–2026 →
   point-in-time CEF CIK membership (org type 32). FREE.
2. Generalize cef_events.py from Saba-only to multi-filer + termination forms.
   FREE.
3. NAV/price backfill — Tiingo free tier for a ~20-fund pilot first; full
   universe needs one month of Tiingo Power (~$10–30) — a PURCHASE for
   Jonathan to make, not an automated step.
4. Discount table with glitch guard; matched-control study runner per brain/30.
