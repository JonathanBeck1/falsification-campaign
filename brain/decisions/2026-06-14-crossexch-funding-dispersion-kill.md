# Decision: Cross-Exchange Perp Funding Dispersion (T31)

Pre-registration: `research/crossexch_funding_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — real, highly-significant funding dispersion that is an order of magnitude too small to clear two-venue fees

The same perp DOES carry different funding on Binance vs OKX at the same 8h
timestamp — the dispersion is real and gross t≈51 — but mean |dispersion| is
0.58 bps/interval against a 20 bps two-venue round trip (break-even hold ≈ 35
intervals / 11.6 days). After cost the harvest is NEGATIVE. Dead on arrival,
exactly as pre-registered.

## Numbers (after-cost, PRIMARY = per-8h-interval harvest)

| metric | value |
|---|---|
| N (matched 8h timestamps) | 241 (4,579 symbol-obs, 19 symbols) |
| overlap window | 2026-03-12 .. 2026-05-31 (OKX-bounded, ~3 mo) |
| gross mean \|dispersion\| | +0.577 bps / interval (t = +51.0) |
| round-trip cost (2 venues × open+close) | 20.0 bps (5 bps/leg) |
| break-even hold | 34.7 intervals ≈ 11.6 days |
| after-cost mean (5 bps/leg, amort. 21 int.) | **−0.376 bps / interval (t = −33.3)**, win 2% |
| after-cost mean (10 bps/leg stress) | −1.328 bps / interval (t = −117.5), win 0% |
| IS \|d\| (signed) | +0.612 bps (−0.143), n=118 |
| OOS \|d\| (signed) | +0.542 bps (−0.087), n=123 |
| placebo (venue-shuffle signed) | +0.001 bps vs real −0.114 bps |

## Gate result (each line PASS/FAIL)

- PASS: N = 241 timestamps (need ≥ 30)
- **FAIL: after-cost mean = −0.376 bps, t = −33.3 (need > 0 & |t| ≥ 2)**
- **FAIL: dispersion > cost — break-even 34.7 intervals > 21 (mean |d| 0.58 bps ≪ 20 bps round trip) → DEAD ON ARRIVAL**
- PASS: OOS sign stable (IS −1.43e-5, OOS −8.65e-6 — both negative signed A−B)
- PASS: placebo — venue-shuffle collapses signed mean to ~0 (+1.2e-7 vs −1.1e-5)
- too-good tripwire: gross Sharpe-like t=51 triggered inspection → top contributors
  are the illiquid alts (DOT 1.02 bps, OP 0.91, FIL 0.84), consistent with
  larger index/cap divergence on smaller names, NOT a data glitch; effect is
  pervasive (all 19 symbols positive |d|), not driven by < 5 names.

## Artifact class (if killed)

**Friction-scale noise (class #2, brain/30).** The signal is genuinely real in
bps (and statistically overwhelming gross) but smaller than round-trip cost — the
exact SPY/IVV "28 survivors" pattern transplanted to crypto venues. The placebo
and OOS checks PASS (the dispersion is real and sign-stable); the kill is purely
that 0.58 bps/interval cannot pay a 20 bps two-venue round trip. This is the
honest control the prompt demanded, and it is decisive and window-independent.

## Honest verdict (2–4 sentences)

Cross-venue funding dispersion is real, pervasive across all 19 matched perps,
sign-stable IS→OOS, and survives the venue-shuffle placebo — but at ~0.58 bps per
8h interval it is roughly 35× too small to clear the fees of running matched
taker positions on two venues (20 bps round trip at 5 bps/leg; worse at 10).
After cost the strategy loses on 98% of intervals. This kill does NOT prove that
event-driven dispersion spikes (a venue's cap binding during a squeeze) are
unharvestable, nor does it cover maker-rebate or single-prime-margin structures
that could cut the fee wall; it also rests on a short OKX-bounded ~3-month window
(the public OKX funding endpoint serves only ~283 rows, and Bybit was geoblocked
HTTP 403 from this environment). But the cost wall is window-independent, so a
longer history would not revive the unconditioned harvest.

## Files

- `src/trader/catalysts/crossexch_funding.py` — pure core (OKX parse, 8h-grid
  alignment, dispersion panel, two-venue cost/break-even, placebo, gate) + OKX
  fetcher behind an injectable HTTP seam
- `tests/financial/test_crossexch_funding.py` — 18 network-free tests
- `scripts/run_crossexch_funding_study.py` — end-to-end runner
- `data/crossexch_funding_results.txt` — raw run output
- `research/crossexch_funding_preregistration.md` — pre-registration

## Registry status update line (paste into brain/34)

`- ❌ **T31** Cross-exchange perp funding dispersion (Binance vs OKX) — *real & sign-stable gross dispersion 0.58 bps/8h (t=51), but ≪ 20 bps two-venue round trip → after-cost −0.38 bps/interval (t=−33), KILL; friction-scale noise. Bybit geoblocked (403), OKX public history ~3 mo wall.*`
