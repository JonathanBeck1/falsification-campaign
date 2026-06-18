# Decision: Buyback-Announcement Drift (T41)

Pre-registration: `research/buyback_drift_preregistration.md`. Falsify-first.

## Verdict

### ❌ KILL — the pre-registered gate PASSED, but on a fiction: the drift is friction-scale noise in illiquid small caps that flips sign OOS once costs are realistic.

The headline is unusual for this campaign: the broad cohort passes **every**
pre-registered gate line (after-cost +1.08%, t=+3.39; net-of-matched +1.52%,
t=+4.17; OOS sign-stable). But that pass is an artifact of the pre-registered
**flat 15 bps** cost applied to a cohort that is **64% sub-$10M/day** and
**41% sub-$2M/day**. The mandatory too-good tripwire (a clean full-gate pass in
a 19-for-19 kill campaign) forced a top-5 + liquidity inspection, and that
inspection kills it three independent ways (below).

## Numbers (after-cost, PRIMARY window car_p1_p21 = [+1,+21])

| metric | value |
|---|---|
| N (usable) | 1,303 |
| gross mean | +1.23% |
| after-cost mean (flat 15 bps, as pre-registered) | +1.08% |
| after-cost t-stat | +3.39 |
| median | +0.67% (mean ≫ median → right-skew tail) |
| win rate | 53.3% |
| IS mean (t) | +1.25% (t=+2.87), n=451 |
| OOS mean (t) | +1.00% (t=+2.31), n=852 |
| matched (ticker,year) placebo mean (t) | **−0.28% (t=−1.62)** |
| net of matched control (Welch t) | +1.52% (t=+4.17) |

## Gate result (each line PASS/FAIL — as pre-registered)

- **PASS:** N=1,303 (need ≥ 30).
- **PASS:** after-cost PRIMARY mean=+1.08%, t=+3.39 (need > 0 & |t| ≥ 2).
- **PASS:** OOS sign stable, IS=+1.25% (n=451), OOS=+1.00% (n=852).
- **PASS:** matched placebo |t|=1.62 < 2 (placebo "null" by the letter).
- **PASS:** net of matched control +1.52%, t=+4.17 (need > 0 & |t| ≥ 2).
- **Too-good tripwire: TRIGGERED** — a clean full-gate pass + median far below
  mean + a *negative* placebo auto-mandated the placebo/contributor/liquidity
  inspection below, which is decisive.

## Why it is still a KILL (the tripwire inspection)

The gate is a *necessary* filter, not *sufficient*; brain/30's rule is "after-cost
expectancy is the ONLY ranked metric" and "friction realism on every leg." The
pre-registered 15 bps was the defensible-but-generous number; it is fiction for
this cohort. Three independent post-gate checks (script
`scripts/diag_buyback_drift_liquidity.py`, output
`data/buyback_drift_liquidity_diagnostic.txt`) each overturn the result:

1. **Liquidity composition (the smoking gun).** Trailing-20d median dollar
   volume at the event: p25 = **$0.45M/day**, p50 = $4.55M/day; **41.4%** of
   events trade **< $2M/day** and **63.7% < $10M/day**, at a median price of
   ~$28. This is a small-/micro-cap cohort, not a tradeable large-cap one.

2. **Realistic tiered cost flips the sign.** Replacing the flat 15 bps with a
   *conservatively low* liquidity-tiered round trip (10 bps for ≥ $50M/day …
   up to 300 bps for < $0.5M/day) gives an after-cost mean of **−0.97%
   (t=−3.04)** — the entire drift is friction. A real book pays the spread the
   pre-reg waved away.

3. **The tradeable sub-cohort collapses AND flips OOS.** Restrict to names a
   real book could trade (≥ $10M/day, N=208): gross drift falls to **+0.38%**,
   after realistic cost **+0.205% with t=+0.32** (insignificant), and the
   IS/OOS split is a clean **sign flip: IS +3.29% (n=54) → OOS −0.64%
   (n=154)**. Whatever drift existed in liquid names in 2015-19 is gone /
   negative in 2020-25.

Supporting contaminants (not load-bearing on their own):
- **Wrong-instrument glitch (class #3/#4):** two top-5 contributors, **ETCG
  (+55.8%) and BCHG (+44.1%)** filed 2022-03-07, are **Grayscale Ethereum
  Classic / Bitcoin Cash Trusts** (verified via EDGAR CIKs 1705181 / 1732409) —
  trust-unit "repurchase" language, not operating-company buybacks; their CARs
  are crypto-premium noise. Dropping crypto trusts + 1% winsorizing leaves the
  *raw* number high (+0.99%, t=3.63), which is exactly the point: **the problem
  is systematic small-cap composition, not five outliers.**
- **Negative placebo inflates "net of matched."** The matched same-ticker
  non-event windows average **−0.28%**: these small caps drift *down* between
  events, so cohort-minus-matched (+1.52%) overstates the signal. The "net"
  passes only because the control is negative, not because the event window is
  strongly positive on a tradeable basis.

## Artifact class (brain/30)

**Primary: #2 Friction-scale noise** — a real ~1% gross bump that is smaller
than realistic round-trip cost for the illiquid names that carry it; it
survives only the generous pre-registered flat cost. **Secondary: #3/#4
data-glitch / wrong-instrument** (crypto-trust contaminants) and a **decayed
effect** in the one tradeable slice (liquid sub-cohort IS→OOS sign flip).

## Honest verdict (2–4 sentences)

Buyback-announcement 8-Ks do show a positive raw ~1.2% market-adjusted CAR over
[+1,+21], and the broad cohort clears every pre-registered gate line — but the
drift lives in sub-$10M/day small caps where the pre-registered 15 bps cost is
fiction; under conservatively-low liquidity-tiered costs the after-cost mean is
**−0.97% (t=−3.04)**, and the only tradeable slice (≥ $10M/day) is insignificant
(t=+0.32) and sign-flips out of sample (IS +3.29% → OOS −0.64%). This is the
mega-cap-drift baseline artifact's mirror image — a *small*-cap illiquidity
premium masquerading as a signaling edge — and it is uncapturable after honest
friction. This KILL does **not** prove every buyback subtype is dead: a
deep-value or accelerated-repurchase sub-cohort, or a long-horizon (≥ 1-yr) ILV
test, is untested here; it proves the broad, mechanically-defined
announcement-drift trade earns nothing a real book can keep.

## Files

- `src/trader/catalysts/buyback_drift.py` — pure core (CAR, dedup, matched
  control, gate); no I/O.
- `tests/financial/test_buyback_drift.py` — 24 network-free unit tests.
- `scripts/run_buyback_drift_study.py` — end-to-end runner (EDGAR + yfinance).
- `scripts/diag_buyback_drift_liquidity.py` — the decisive liquidity/cost
  interrogation.
- `research/buyback_drift_report.md` — full live run output (gate PASS).
- `data/buyback_drift_results.txt` — raw run output.
- `data/buyback_drift_liquidity_diagnostic.txt` — diagnostic output (the KILL).
- `output/catalysts/buyback_drift_study.json` — machine-readable summary.

## Registry status update line (paste into brain/34)

`- ✅ **T41** Buyback-announcement drift (8-K Item 8.01, excl 2.02) — *KILL (friction-scale, class #2): broad cohort PASSES the full pre-reg gate (after-cost +1.08%, t=+3.39; net-of-matched +1.52%, t=+4.17; OOS sign-stable, N=1303) but the cohort is 64% sub-$10M/day, 41% sub-$2M/day — the pre-reg flat 15bps is fiction. Liquidity-tiered cost → −0.97% (t=−3.04); tradeable slice (≥$10M/day, N=208) +0.21% (t=+0.32) and IS +3.29% → OOS −0.64% sign-flip. Crypto-trust glitch tail (ETCG/BCHG); negative −0.28% placebo inflates the "net". A small-cap illiquidity mirage, not a signaling edge.*`
