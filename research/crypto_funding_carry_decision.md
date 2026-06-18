# Decision: Perp Funding-Rate Carry, cross-sectional alt tail (T29)

Pre-registration: `research/crypto_funding_carry_preregistration.md`. Falsify-first.
**A risk-premium-not-alpha kill — and the funding-vs-price decomposition is the
smoking gun that names exactly why.**

> **Re-run note (2026-06-17) — canonical numbers.** T29 was re-run on the
> epoch-fixed data (matched 80-symbol cohort). The figures in the body below are
> the earlier 2026-06-14 run and are **superseded**; the verdict (KILL,
> risk-premium-not-alpha) and every sign are unchanged. Canonical headline numbers
> (matching `brain/34`, the scoreboard, and `PAPER_DRAFT.md` §7): after-cost
> **−2.6%/yr (t = −0.05)**; **+31.6%/yr** funding ~**81%** repaid by the short-leg
> price PnL (**−25.7%/yr**) + ~8.5%/yr taker fees; gross IS **+18 → −19 bps/day**
> OOS; survivorship 18/80 (=23%) dead, survivor-only ≈ cohort. Source:
> `data/crypto_funding_carry_results.txt` ("Run 2026-06-17").

## Verdict

### ❌ KILL — the delta-neutral funding carry is flat-to-negative after costs; the gorgeous +31%/yr funding yield is almost entirely paid back by the short-perp price leg (it's compensation for being short a rising/reverting asset, a risk premium, not free carry) and the gross signal sign-flips IS→OOS.

## Numbers (after-cost, PRIMARY = daily book return, survivorship-aware cohort)

| metric | value |
|---|---|
| N (days, ≥5 names) | **252** |
| after-cost mean / day | **−0.41 bps** (−0.000041) |
| t-stat | **−0.03** |
| annualized return | **−1.50%** |
| Sharpe (ann) | −0.01 |
| win rate | 53.2% |
| IS 2020-01..2023-01 mean (t) | **+17.0 bps/day (t=+0.96)**, n=1068 |
| OOS 2023-01..2025-12 mean (t) | **−17.4 bps/day (t=−0.90)**, n=1096 |
| placebo (random-decile) mean (t) | −18.6 bps/day (t=−1.24) |
| alt-tail-only mean (t) | +0.6 bps/day (t=+0.05) |

### Funding-vs-price decomposition (per day, pre-cost) — THE result

| component | per day | annualized |
|---|---|---|
| **funding collected** | **+86.3 bps** | **+31.5%/yr** |
| **short-leg price PnL** | **−67.2 bps** | **−24.5%/yr** |
| turnover cost | −23.2 bps | −8.5%/yr |
| **= net book** | **−4.1 bps** | **−1.5%/yr** |

The funding component is large and positive, exactly as the mechanism predicts —
retail-long crowding pays the short a fat +31.5%/yr gross funding yield. But under
the (idealized) delta-neutral book the short-perp **price** leg gives back −24.5%/
yr: the very tokens paying the most funding are the ones whose price tends to rise
(the longs crowding them are *directionally right* often enough), so the price loss
on the short eats ~78% of the funding. The thin residual (+7%/yr gross) is then
fully consumed by honest taker friction (−8.5%/yr on turnover), landing the net at
−1.5%/yr. Funding "dominating" the decomposition is therefore NOT a pass — it
dominates a return that nets to zero.

## Gate result (each line PASS/FAIL)

- **PASS**: N = 252 days with ≥5 names (need ≥ 30).
- **FAIL**: after-cost mean = −0.41 bps/day, t = −0.03 (need > 0 & |t| ≥ 2).
- **FAIL**: OOS sign stability — IS +17.0 bps/day flips to OOS −17.4 bps/day.
- **PASS (info, not a pass for the claim)**: funding dominates price in the
  decomposition (+86 vs −67 bps) — but the net is negative, so this only
  *explains* the kill, it does not rescue it.
- **PASS**: placebo ≈ 0 — random-decile mean −18.6 bps/day, t = −1.24 (|t| < 2);
  the cohort does not beat a random basket.
- **Tripwire**: not tripped (Sharpe −0.01, win 53%) — no too-good artifact to chase.

## Survivorship verdict (the whole point of the foundation)

**Survivorship was handled honestly and is NOT what killed it.** The universe was
built from Binance's append-only public archive `data.binance.vision`, which
**retains delisted perps** — of 79 sampled symbols, **18 (23%) are delisted**
(SRMUSDT, BTSUSDT, etc.; funding spans ending 2024 vs a 2026-06 frontier). The
survivor-only re-run is essentially identical (−1.67 bps/day vs cohort −0.41 bps):
the cohort−survivor gap is **+1.26 bps/day**, i.e. including the corpses *slightly
helped* in this sample (their pre-death funding collection marginally outweighed
their terminal price collapse). So this kill is real, not a survivor mirage — and
notably the bias here ran the *opposite* direction from the usual crypto-carry lie
(where dropping dead tokens manufactures fake carry). We measured both and report
the gap.

## Artifact class (brain/30 taxonomy)

**Risk-premium-not-alpha / decayed-effect**, with a friction-scale assist. The
"edge" is real funding income but it is compensation for a real short-perp price
risk (the price leg eats it), not a free lunch — adjacent to the friction-scale-
noise class in that the surviving sliver is then smaller than taker cost. Plus a
clean OOS decay (the gross IS signal does not survive into 2023-2025). No look-
ahead, no data glitch, no survivorship mirage — the decomposition and the placebo
isolate the cause cleanly.

## Honest verdict (2-4 sentences)

A naive crypto funding-carry backtest would have printed +31%/yr and called it an
edge; the pre-registered funding-vs-price decomposition shows ~78% of that is paid
straight back by the short-perp price leg and the rest by taker fees, netting
−1.5%/yr after cost with a t of essentially zero and an IS→OOS sign flip. The
mechanism (retail-long crowding → positive funding) is *real* — funding genuinely
is +31%/yr on the top decile — but it is a compensated risk premium, not alpha:
you are paid to warehouse the directional risk the crowd is taking. This kill does
NOT prove every funding strategy on every venue/horizon is dead (a truly market-
neutral, basis-hedged, lower-turnover implementation on a different fee tier is a
separate pre-registration); it kills the daily, equal-weight, top-decile, taker-
priced Binance-UM expression as specified.

## Files

- `src/trader/catalysts/crypto_data.py` — survivorship-aware Binance archive
  foundation (pure parse core + injectable HTTP seam; retains delisted symbols).
- `src/trader/catalysts/crypto_funding_carry.py` — pure carry engine + gate
  (panels, top-decile short book, funding/price decomposition, IS/OOS, placebo).
- `tests/financial/test_crypto_data.py` — 20 network-free tests.
- `tests/financial/test_crypto_funding_carry.py` — 10 network-free tests.
- `scripts/run_crypto_funding_carry_study.py` — end-to-end runner (live, free).
- `data/crypto_funding_carry_results.txt` — raw run output.

## Registry status update line (paste into brain/34, replaces the ⬜ T29 stub)

`- ✅ **T29** Perp funding carry, cross-sectional alt tail — *KILL: after-cost −1.5%/yr (t=−0.03), IS +17bps/day flips to OOS −17bps/day. Funding +31.5%/yr gross is real but ~78% paid back by the short-perp price leg + the rest by ~6bps taker fees → risk premium, not alpha. Survivorship handled honestly via data.binance.vision (retains delisted; 18/79=23% dead); survivor-only ≈ cohort (gap +1.3bps), so NOT a survivor mirage. Placebo (random decile) also ~0.*`
