#!/usr/bin/env python
"""Bounded survival estimate for the CEF discount-capture convex bet.

A precise survival backtest needs the resolved funds' entry+terminal market
prices, which are NOT freely available (yfinance purges delisted tickers;
stooq/CEFConnect blocked; filing-based entry-price reconstruction is error-prone).
So this is an explicit BOUND, not a backtest: it combines the *measured*
resolution data (from research/cef_resolution_report.md) with a defensible
entry-discount assumption and a friction haircut, across a sensitivity grid.

Economics: a follower holding a tilted basket of Saba CEF targets to resolution
earns the asset-class (NAV) return PLUS a discount-capture alpha. On resolution
(tender/liquidation/merger/open-end) the entry discount closes to ~0 -> captured.
Non-resolvers earn ~0 alpha (the broad 6m study found survivor excess ~median 0).

  per-campaign discount alpha over the hold = resolution_rate * entry_discount - friction
  annualized ~= (1 + that) ** (1/hold_years) - 1

All inputs are stated; treat outputs as an order-of-magnitude bound.
"""

from __future__ import annotations

# --- Measured / documented inputs ------------------------------------------
# Resolution rates from research/cef_resolution_report.md (agent-extracted from
# hard EDGAR filings). 0.40 is the cross-sectional LOWER BOUND (right-censored);
# the censoring-adjusted long-run rate is higher. The tilt (muni + fast sponsors
# Tortoise/ClearBridge/MFS/Pioneer/BlackRock) raised the observed rate to ~55-70%.
RESOLUTION_RATES = {
    "untilted (lower bound)": 0.40,
    "untilted (censoring-adj)": 0.50,
    "tilted muni+fast sponsor": 0.60,
    "tilted (optimistic)": 0.70,
}
# Entry discount of a Saba target when the 13D is filed. Activist CEF targets
# (and Saba's public targets) typically trade at ~8-15% discounts to NAV; we
# sweep a conservative-to-rich band. This is the key assumption (unverified here
# for lack of free NAV data) -- hence the sensitivity.
ENTRY_DISCOUNTS = [0.06, 0.10, 0.14]
FRICTION_ROUND_TRIP = 0.01   # CEF spreads/impact, once per ~2yr hold
HOLD_YEARS = 2.0             # measured median time-to-resolution ~2.0 yr
NONRESOLVER_ALPHA = 0.0      # broad study: survivor excess ~0


def annualized(total: float, years: float) -> float:
    return (1.0 + total) ** (1.0 / years) - 1.0


def main() -> int:
    rows = ["# CEF Discount-Capture — Bounded Survival Estimate", "",
            "NOT a backtest (resolved-fund prices unavailable free). A bound from the",
            "measured resolution rates x an assumed entry discount, minus friction.",
            "Alpha is *over* the asset-class/NAV return a held basket also earns.", "",
            f"Assumptions: hold = {HOLD_YEARS} yr (measured median to resolution), "
            f"friction = {FRICTION_ROUND_TRIP*100:.0f}% round-trip, non-resolver alpha = 0.", "",
            "## Annualized discount-capture alpha (over asset class)", "",
            "| basket | resolution rate | entry discount 6% | 10% | 14% |",
            "|---|---|---|---|---|"]
    for name, rate in RESOLUTION_RATES.items():
        cells = []
        for d in ENTRY_DISCOUNTS:
            total = rate * d + (1 - rate) * NONRESOLVER_ALPHA - FRICTION_ROUND_TRIP
            cells.append(f"{annualized(total, HOLD_YEARS)*100:+.1f}%")
        rows.append(f"| {name} | {rate:.0%} | {cells[0]} | {cells[1]} | {cells[2]} |")

    rows += ["", "## Read",
             "",
             "- Central case (tilted ~60% resolution, ~10% entry discount): "
             f"**~{annualized(0.60*0.10 - FRICTION_ROUND_TRIP, HOLD_YEARS)*100:.1f}%/yr** "
             "discount-capture alpha over the asset class.",
             "- Plausible range across the grid: roughly **+0.7% to +3.6%/yr**.",
             "- This is a SLOW (~2yr holds), CONVEX (≈half the basket does nothing), "
             "capacity-limited overlay -- real but modest, never life-changing.",
             "- Capital efficiency is poor: the ~40-50% that don't resolve tie up "
             "capital for years earning only the asset-class return.",
             "",
             "## What would make it precise (not done here)",
             "- Resolved funds' entry+terminal prices (a free Tiingo key retains "
             "delisted EOD), OR per-fund liquidation/merger terminal values parsed "
             "from N-8F / final N-CSR / N-14 filings.",
             "- Real entry discounts (price vs NAV) per fund to replace the assumed "
             "band -- needs a NAV source (N-CSR parsing or a CEF data feed).",
             ""]
    out = "\n".join(rows) + "\n"
    from pathlib import Path
    Path(__file__).resolve().parent.parent.joinpath("research", "cef_survival_estimate.md").write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
