# Decision: Single-Name Earnings IV Crush (T23)

Pre-registration: `research/earnings_iv_crush_preregistration.md`. Falsify-first.
Run output: `data/earnings_iv_crush_results.txt`, `output/catalysts/earnings_iv_crush_study.json`.

## Verdict

### KILL — pre-earnings IV does overstate the realized move (+1.59% crush gap), but the tradeable short straddle loses −0.59%/event (t=−3.61) after honestly crossing the wide single-name bid/ask, and it does not beat ordinary short-vol carry.

## Numbers (after-cost, PRIMARY = short-straddle return as fraction of spot)

| metric | value |
|---|---|
| N (usable events) | 414 (24/24 names) |
| after-cost mean | **−0.593% of spot** |
| after-cost t-stat | **−3.61** |
| median | −0.040% |
| win rate | 49.3% |
| Sharpe (across events) | −0.177 |
| mean priced move (straddle/spot) | 7.06% |
| mean realized move | 5.47% |
| **crush gap (priced − realized)** | **+1.59%** (median +1.92%) |
| corr(P&L, realized move) | −0.843 |
| placebo (non-earnings) mean | −0.448% (t=−13.18, n=720) |
| earnings premium over placebo | −0.146% (Welch t=−0.87) |
| IS mean (≤2023) | −0.397% (n=183, t=−1.61) |
| OOS mean (>2023) | −0.749% (n=231, t=−3.41) |
| worst event | NFLX 2022-04-19 −23.2% |
| sum of 5 worst | −81.5% of spot |
| mean ex-worst-5 | −0.401% (still negative) |

## Gate result (each line PASS/FAIL)

- PASS: N=414 (need ≥ 30).
- **FAIL: after-cost mean=−0.593% t=−3.61 (need > 0 and |t| ≥ 2).**
- PASS (perversely): OOS sign stability — IS −0.40%, OOS −0.75%, both negative,
  both N ≥ 10. The strategy is *reliably* a loser in and out of sample.
- **FAIL: earnings minus non-earnings placebo Welch t=−0.87 (need ≥ 2).** The
  earnings short straddle does not even beat the ordinary one-day short-vol carry.

Too-good tripwire: n/a (result is negative, not too-good). Bottom-5/top-5
inspected anyway: the deaths are the canonical mega-gaps (NFLX −23%, AVGO −16%,
META −14%); the wins top out at +7%. Asymmetry is the whole story.

## Why it fails (the mechanism, decomposed)

The hypothesis is *half right and it does not matter*:

1. **IV genuinely overstates the move.** Across 414 events the priced move
   (7.06%) exceeds the realized move (5.47%) by a mean +1.59% / median +1.92%.
   Pre-earnings ATM IV is, on average, too high. That part of the thesis holds.
2. **But the premium is fully consumed by friction + the tail.** Single-name
   option spreads are wide; selling the straddle to the bid and buying it back at
   the ask on each leg, plus commission, costs more than +1.59% of spot on
   average — so the *tradeable* after-cost return is −0.59% (t=−3.61),
   sign-flipped from the gross crush gap.
3. **It is compensated jump variance, not alpha.** corr(after-cost P&L, realized
   move) = −0.843: the losses ARE the big earnings gaps. The seller is paid the
   crush premium precisely as compensation for bearing those gaps, and the price
   of that insurance (the spread the buyer pays) is set so the seller does not
   come out ahead. This is the exact lesson the pre-reg flagged from T43.
4. **No earnings-specific edge over plain short vol.** The non-earnings placebo
   one-day short straddle also loses (−0.448%), and the earnings premium over it
   is −0.146% (Welch t=−0.87, indistinguishable). Whatever the earnings short
   straddle is, it is not better than being short vol on a random day.

The tail is brutal but is not even the binding constraint: removing the 5 worst
events still leaves a −0.401% mean. The typical event loses after costs; the
gaps merely make it worse. ("Deaths dominate" registers False only because the
mean is already negative without them.)

## Artifact class (brain/30 taxonomy)

**Friction-scale signal that sign-flips (class 2), compounded by compensated
jump-risk variance.** The gross crush gap (+1.59%) is real but smaller than the
honest round-trip single-name option spread; ranking on the gross/mid-to-mid
number would have flattered the strategy. This is the same shape that killed the
SPY/IVV "28 survivors" (T-ledger #4) and the VRP condor (T19): a real but
sub-friction effect, here also riding a catastrophic left tail.

## Honest verdict (2–4 sentences)

Pre-earnings IV overstates the realized single-name earnings move — but the
overstatement (~1.6% of spot) is smaller than the cost of honestly trading the
wide single-name straddle around the print, so the short-straddle P&L is
significantly NEGATIVE (−0.59%/event, t=−3.61) and reliably so in and out of
sample, while the loss distribution is dominated by NFLX/META/AVGO mega-gaps
(corr P&L↔move = −0.84). The "edge" is compensated jump-risk variance, not
alpha, and it does not even beat ordinary non-earnings short-vol carry. This
KILL does not prove IV never overstates the move (it does, grossly); it proves
the premium is uncapturable after friction for these 24 names EOD-to-EOD.

## Data wall encountered (and resolved at pre-reg, not papered over)

The lake's `underlying_close` is NULL and the foundation's yfinance fallback
returns **split-adjusted** closes that do not match the lake's *as-of-trade-date*
(unadjusted) strikes for names that split after the trade date (verified: AVGO
10:1 Jul-2024 and the NFLX series both come back ~10× wrong, putting "ATM" on a
deep-ITM strike and yielding absurd IVs of 290% collapsing to 1%). Using the
foundation's `atm_iv`/yfinance spot directly would have been a derived/fake-data
artifact (class 4). Resolved by anchoring spot from the option chain itself via
**put-call parity** (recovers NFLX = $326.44 on 2023-01-18, consistent with the
strikes), and by computing the P&L from the lake's own bid/ask — so the result
never depends on the broken external spot series. This is a real, documented
limitation of the shared foundation that downstream strike-based tests must
handle the same way.

## Files

- `src/trader/catalysts/earnings_iv_crush.py` — pure core (parity spot anchor,
  ATM selection, honest bid/ask straddle P&L, tail report, gate).
- `tests/financial/test_earnings_iv_crush.py` — 27 network-free unit tests.
- `scripts/run_earnings_iv_crush_study.py` — end-to-end runner (lake + yfinance).
- `research/earnings_iv_crush_preregistration.md` — pre-reg (written first).
- `data/earnings_iv_crush_results.txt`, `output/catalysts/earnings_iv_crush_study.json` — raw output.

## Registry status update line (paste into brain/34)

`- ❌ **T23** single-name earnings IV crush — *KILL: pre-earnings IV overstates the move (+1.59% crush gap) but the short straddle loses −0.59%/event (t=−3.61) after honest single-name bid/ask + tail; corr(P&L, move)=−0.84 = compensated jump variance, not alpha; doesn't beat non-earnings carry (Welch t=−0.87). N=414, 24 names. Class-2 friction-scale + jump-risk tail.*`
