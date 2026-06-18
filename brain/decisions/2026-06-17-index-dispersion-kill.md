# Decision: Index Dispersion / Correlation Risk Premium (T22)

Pre-registration: `research/index_dispersion_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — the correlation risk premium is real (gross t≈2) but is entirely consumed by single-name option spreads (friction = 365% of the gross edge)

Index IV genuinely embeds more correlation than realizes — mean implied ρ = 0.380
vs mean realized ρ = 0.349 over 53 monthly rebalances, and the **gross**
vega-neutral dispersion book earns +5.4%/period of index premium (t = +1.98, win
58%). But the long leg is 26 single-name straddles whose realized quoted half
-spreads are ~3.7× the gross edge. **After** the actual spreads the book is
−14.2%/period (t = −5.03, win 21%), OOS-stable in both halves. The premium exists;
it is uncapturable at retail single-name friction. Exactly the pre-registered
"structurally capacity-limited — expensive to harvest."

## Numbers (PRIMARY = per-rebalance dispersion return, normalized by index premium)

| metric | value |
|---|---|
| N (monthly rebalances) | 53 |
| window | 2022-01-03 .. 2026-06-12 (full lake) |
| basket | 26 equal-weighted mega-cap constituents (proxy for QQQ) |
| mean implied ρ | +0.380 |
| mean realized ρ | +0.349 |
| **correlation premium (imp − real)** | **+0.031** |
| GROSS mean / period | +0.0536 (t = +1.98, win 58%) |
| mean friction / period | +0.1955 (= **365% of gross edge**) |
| **NET mean / period** | **−0.1419 (t = −5.03, win 21%)** |
| NET annualized | −1.70 |
| NET worst period / max drawdown | −0.686 / −7.02 (cum) |
| IS net (≤2024-03-31) | −0.1172 (t = −3.36, N = 27) |
| OOS net (≥2024-04-01) | −0.1675 (t = −3.73, N = 26) |
| incremental alpha over short-index-vol | −0.1344 (alpha_t = −5.47) |
| corr(net return, index move) | +0.03 |
| sign-flip placebo p | 1.0000 |
| split-guard drops | a handful of name-periods (NVDA/AVGO/AMZN/GOOGL/TSLA splits) |

## Gate result (each line PASS/FAIL)

- PASS: N = 53 (need ≥ 30)
- **FAIL: after-cost mean = −0.142, t = −5.03 (need > 0 & |t| ≥ 2)**
- **FAIL: incremental alpha over short-index-vol = −0.134, alpha_t = −5.47 (need > 0 & |t| ≥ 2)**
- PASS: OOS sign stable (IS −0.117, OOS −0.168 — both negative)
- **FAIL: placebo beaten (sign-flip p = 1.0000 — the net loss is so robust no sign-flip reaches it)**
- too-good tripwire: n/a (the book loses; nothing to flag)

## Artifact class (if killed)

**Friction-scale noise (class #2, brain/30).** This is the SPY/IVV "28 survivors"
pattern and the T31 cross-venue funding pattern transplanted to index options: a
genuinely real, statistically-supported gross signal (gross t ≈ 2; implied ρ >
realized ρ as the literature says) that is smaller than the cost of harvesting it.
The kill is NOT a compensated-risk story — corr(return, index move) is only +0.03,
so in this sample the loss is not crash compensation; KEY CONTROL 2's |index-move|
beta is negative and its alpha is insignificant. The loss is purely that 26
single-name straddle round-trips at realized spreads cost 3.65× the gross
dispersion premium.

## Honest verdict (2–4 sentences)

The correlation risk premium is real in this data — index implied correlation
(0.38) runs above subsequently-realized correlation (0.35), and an idealized,
frictionless vega-neutral dispersion book earns a marginally-significant +5.4% of
index premium per month (t ≈ 2). It does not survive contact with the order book:
charging the *actual* quoted half-spreads on 26 single-name straddles (entry and
exit) costs 3.65× the gross edge, turning the book into a −14%/month, t = −5
loser that is sign-stable in and out of sample. This KILL does not claim the
correlation premium is fake (it is not) or that institutional dispersion desks
cannot harvest it with internalized flow / maker rebates / cap-faithful baskets —
it shows the *retail, EOD-marked, single-name-spread* version is dominated by
friction, and it rests on a 26-name equal-weighted **proxy** for QQQ (no MSFT,
equal not cap weights), so the ρ numbers are descriptive of the mega-cap subset.

## Files

- `src/trader/catalysts/index_dispersion.py` — pure core (implied/realized average
  correlation, vega-neutral book, realized-spread friction, gate stats)
- `tests/financial/test_index_dispersion.py` — 19 network-free tests
- `scripts/run_index_dispersion_study.py` — end-to-end runner
- `data/index_dispersion_results.txt` / `.csv` — raw run output
- `research/index_dispersion_preregistration.md` — pre-registration

## Registry status update line (paste into brain/34)

`- ❌ **T22** Index dispersion / correlation risk premium (QQQ vs 26 constituents) — *real premium (implied ρ 0.38 > realized ρ 0.35; GROSS t=1.98) but single-name spreads = 365% of edge → after-cost −14%/mo (t=−5.03), OOS-stable, KILL; friction-scale noise (class #2). 26-name equal-weight proxy for QQQ.*`
