# Pre-Registration — CEF Discount-Capture Survival Backtest (REAL)

**Status:** pre-registered design. Replaces the bounded *estimate*
(`research/cef_survival_estimate.md`) with an actual realized backtest, blocked
until now only by missing delisted-fund prices.

## Motivation

The 6-month follower event study (`cef_activist_study_report.md`) FAILED: the only
robust effect (a +1m pop) nets to ~0 after CEF spreads. The resolution analysis
(`cef_resolution_report.md`) then showed ~40% of Saba's 82 CEF campaigns RESOLVE
(liquidate / merge / open-end / large tender at NAV) over a ~2yr median, with a
*selection* tilt: muni funds (54% vs 29%) and fast sponsors
(Tortoise/ClearBridge/MFS/Pioneer/BlackRock) resolve more; Invesco/abrdn/BNY Mellon
drag. The bounded estimate put discount-capture alpha at ~1–3%/yr but could not
*measure* it, because the resolved winners delisted and yfinance purges delisted
symbols. This backtest measures the realized number using Tiingo (which retains
delisted EOD) for the survivors.

## Hypothesis

Following Saba's initial SC 13D into a CEF and holding to resolution earns positive
**discount-capture excess** over the broad-CEF market (PCEF), and the
muni+fast-sponsor **tilt** earns MORE than the naive follow-everything basket.

## Design (frozen before looking at realized numbers)

- **Universe:** the 82 Saba CEF campaigns in `output/catalysts/saba_cef_campaigns.csv`.
- **Labels:** resolution outcome + date parsed from `cef_resolution_report.md` §3
  (33 resolved, 49 ongoing). Resolved set = {deregistered, delisted, merger, tender}.
- **Entry:** first target trading day strictly after `filing_date` (t0+1) — the
  earliest a follower could act on the public filing.
- **Exit:** resolution date for resolved campaigns; `min(today, filing + 730d)` for
  ongoing campaigns (a censored, still-running hold). Exit price = last target quote
  on/before the exit date (handles the delisting gap — Tiingo's last mark may
  predate the cash-out).
- **Return:** `target_exit/target_entry − 1` MINUS the PCEF return over the **same
  realized [entry, exit] dates** = NAV-free discount-capture excess. Annualized
  geometrically by realized holding-years.
- **Baskets:** untilted (all priced) vs tilted (`is_municipal OR sponsor in
  {Tortoise, ClearBridge, MFS, Pioneer, BlackRock}`, and DROP equity names at
  {Invesco, abrdn, BNY Mellon}).
- **Stats:** mean / median excess, % positive, t-stat (same machinery as
  `cef_study.py`).
- **Price provider:** yfinance first; Tiingo fallback for delisted. Pure return
  functions operate on price Series and are unit-tested on synthetic data.

## Pre-registered GATE (success condition for the tilt)

The tilt is declared real only if ALL hold:

1. **Enough coverage:** priced N ≥ 20 (so the tilt isn't a 3-fund accident).
2. **Positive & significant:** tilted mean excess > 0 with |t| ≥ 2.
3. **Beats untilted:** tilted mean excess > untilted mean excess.

## What this CANNOT measure (declared up front, no overselling)

- **Terminal NAV payoff.** We see last *traded* price, not the liquidation/merger
  cash-out value, so realized upside is a conservative read of the true payoff.
- **Absolute return.** NAV-free => excess over the CEF market only; a held basket
  also earns the asset-class return.
- **Right-censoring.** Ongoing 2024 names may still resolve; the untilted basket
  understates the eventual resolution rate.
- **Frictions.** ~1% CEF round-trip spread is NOT deducted in the headline; subtract
  before sizing.
- **Coverage risk.** With no Tiingo key the resolved winners are missing entirely and
  the result is biased DOWN — reported as a lower-coverage floor, not the real edge.

## Falsification

If the tilted basket is not positive, not significant, or does not beat untilted, the
discount-capture tilt is NOT supported and the niche stays parked behind SPAC-arb.
A pass is necessary but not sufficient — frictions and the terminal-NAV blind spot
must still be cleared before any sizing.
