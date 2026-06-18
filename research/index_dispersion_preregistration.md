# Pre-registration — T22 Index Dispersion / Correlation Risk Premium

**Status:** design FROZEN before results. Falsify-first.
**Code:** `src/trader/catalysts/index_dispersion.py` (pure core),
`scripts/run_index_dispersion_study.py` (runner),
`tests/financial/test_index_dispersion.py` (19 network-free tests).

## Hypothesis

Index implied variance embeds an **implied average correlation** among its
constituents that is *structurally higher* than the correlation that subsequently
realizes (the documented "correlation risk premium"). If so, a **dispersion
trade** — SHORT the index straddle, LONG a vega-matched basket of single-name
straddles — earns a positive premium when names move apart more than option
prices implied.

**Pre-registered expectation (the mechanism note):** *structurally
capacity-limited — expensive to harvest.* The long leg is ~26 single-name
straddles whose quoted bid/ask is far wider than the index's, so the realistic
prediction is that the gross premium (if present) is consumed by single-name
friction. This test is designed to MEASURE that, not assume it.

## Universe (frozen)

- **Index:** QQQ (Nasdaq-100 ETF), EOD option lake.
- **Constituents:** 26 fully-collected mega-cap names — AAPL, ADBE, AMAT, AMD,
  AMZN, AVGO, BKNG, COST, CSCO, GOOGL, HON, INTU, ISRG, LIN, LRCX, META, MU,
  NFLX, NVDA, PEP, QCOM, REGN, TMUS, TSLA, TXN, VRTX. (GOOG dropped — GOOGL kept —
  so the dual share class is not double-counted.)
- **Window:** 2022-01-03 .. 2026-06-12 (full lake), 21-trading-day non-overlapping
  rebalances, 10-trading-day hold (~14 calendar days).
- **IS/OOS split:** IS ≤ 2024-03-31; OOS ≥ 2024-04-01.

### Acknowledged limitation (documented before results)

The 26-name equal-weighted basket is a **proxy** for QQQ, not a cap-weighted
Nasdaq-100 replication: it omits MSFT (a top weight) and several smaller members,
and uses equal (not cap) weights. So the implied/realized correlation numbers are
descriptive of *this mega-cap subset*, and a clean "tradeable QQQ dispersion"
claim is out of scope. The dispersion **P&L** does not depend on the weighting
being QQQ-faithful — it is the realized straddle book on the available names — but
the mechanism descriptors (ρ_imp, ρ_real) inherit this proxy caveat.

## Construction (frozen)

1. ~30d ATM straddle for index + each constituent, marked from the shared
   `vol_surface_data` foundation (parity-anchored spot, two-sided quotes, IV
   quality band). Friction = **the realized quoted half-spread** from the actual
   ATM call+put bid/ask, crossed at entry AND exit (not an assumed cost).
2. Hold 10 trading days; reprice the SAME (expiration, strike) contracts from the
   actual exit quotes (BS fallback at residual tenor where a leg is no longer
   two-sided).
3. Book: SHORT 1 index straddle, LONG an equal-weighted basket sized
   **vega-neutral** to the index. Normalize the period P&L by the index straddle
   entry premium so the series is return-like.
4. **Split guard:** any name-period with |entry→exit underlying return| > 50%
   (a corporate-action artifact — TSLA 3:1, NVDA/AVGO 10:1, AMZN/GOOGL 20:1 all
   in-window) is dropped and counted.

## Gate (brain/30) and kill criteria — FIXED before results

A SURVIVE requires ALL of:

1. **N ≥ 30** rebalance periods.
2. **After-cost** (realized single-name spreads) mean > 0 AND |t| ≥ 2.
3. **OOS sign stable** — IS and OOS net means same sign, both halves N ≥ 10.
4. **Incremental alpha over short-index-vol** > 0 AND |t| ≥ 2 (the KEY control:
   the book must beat a pure short-index-vol stance, not just be it).
5. **Sign-flip placebo** p < 0.05.
6. **Too-good tripwire** not the basis of the result.

KEY CONTROL 2 (diagnostic, not a hard gate): regress the book on |index move| to
test whether any premium is just compensation for correlation-crash risk
(class 7). **KILL** if the after-cost gate fails; classify by artifact taxonomy.

## What would change the verdict

A larger or cap-faithful basket (incl. MSFT), maker-rebate/internalized execution
that cuts the single-name spread wall, or an event-conditioned dispersion entry
(corr-spike mean-reversion) are explicitly **out of scope** — this is the
unconditioned, retail-friction, EOD-marked harvest only.
