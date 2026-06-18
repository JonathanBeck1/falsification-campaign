# CEF Discount-Capture — Bounded Survival Estimate

NOT a backtest (resolved-fund prices unavailable free). A bound from the
measured resolution rates x an assumed entry discount, minus friction.
Alpha is *over* the asset-class/NAV return a held basket also earns.

Assumptions: hold = 2.0 yr (measured median to resolution), friction = 1% round-trip, non-resolver alpha = 0.

## Annualized discount-capture alpha (over asset class)

| basket | resolution rate | entry discount 6% | 10% | 14% |
|---|---|---|---|---|
| untilted (lower bound) | 40% | +0.7% | +1.5% | +2.3% |
| untilted (censoring-adj) | 50% | +1.0% | +2.0% | +3.0% |
| tilted muni+fast sponsor | 60% | +1.3% | +2.5% | +3.6% |
| tilted (optimistic) | 70% | +1.6% | +3.0% | +4.3% |

## Read

- Central case (tilted ~60% resolution, ~10% entry discount): **~2.5%/yr** discount-capture alpha over the asset class.
- Plausible range across the grid: roughly **+0.7% to +3.6%/yr**.
- This is a SLOW (~2yr holds), CONVEX (≈half the basket does nothing), capacity-limited overlay -- real but modest, never life-changing.
- Capital efficiency is poor: the ~40-50% that don't resolve tie up capital for years earning only the asset-class return.

## What would make it precise (not done here)
- Resolved funds' entry+terminal prices (a free Tiingo key retains delisted EOD), OR per-fund liquidation/merger terminal values parsed from N-8F / final N-CSR / N-14 filings.
- Real entry discounts (price vs NAV) per fund to replace the assumed band -- needs a NAV source (N-CSR parsing or a CEF data feed).

