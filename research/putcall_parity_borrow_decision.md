# Decision: Put-Call Parity / Implied Borrow (T26)

Pre-registration: `research/putcall_parity_borrow_preregistration.md`. Falsify-first.

## Verdict

### ⛔ DATA_WALL — easy-to-borrow universe: the "implied borrow" is a DIVIDEND tilt, not short-supply; cross-sectional return signal is null (after-cost +0.57%, t=+0.64)

This is the pre-registered MOST-LIKELY outcome. The Ofek-Richardson-Whitelaw
hard-to-borrow effect lives in small-cap / heavily-shorted / hard-to-borrow
names; our lake is 24 easy-to-borrow mega-caps + index ETFs. There is no real
borrow dispersion to sort on, the spread does not pay, and — the corrected
mechanism — what dispersion the sort *does* see is **dividend yield, not borrow**.

> **Provenance + mechanism correction (foundation re-run).** Re-generated on the
> parity-anchored-spot foundation (`vol_surface_data.py`, fix commit `bdc1174`),
> which derives the underlying by inverting put-call parity **with dividend yield
> assumed q=0**. The DATA_WALL verdict is unchanged, but the original doc
> mislabeled the mechanism. The chain-implied carry `q*` is, by construction,
> `borrow + dividend yield` (the parity inversion sets div=0, so q\* *absorbs* the
> dividend). On this universe borrow ≈ 0, so **q\* ≈ dividend yield**: the
> per-name q\* correlates with trailing dividend yield at **+0.949**, dividend
> payers carry **positive** q\* (PEP +109, TXN +100, CSCO +87, HON +85, LIN +68,
> QCOM +51 bps/yr) while zero-dividend names carry **negative** q\* (AMD −50,
> TSLA −45, NFLX −38, META −32, ISRG −48 bps/yr). The "high-implied-borrow"
> tercile is therefore the **high-DIVIDEND** tercile — a factor tilt, not
> short-supply pricing. The original doc's stale "yfinance-spot-mismatch +
> American early-exercise; HON −6857 bps pathological" framing no longer applies:
> spot is now parity-derived, and HON's q\* is a benign **+84.7 bps/yr** on the
> re-run. Several universe names pay material dividends (PEP, CSCO, TXN, HON,
> QCOM, AVGO, LIN, TMUS), so the pre-reg's "~0-dividend tech/large-caps" premise
> (pre-reg §4) was itself wrong — which is exactly *why* q\* is not borrow here.

## Numbers (after-cost, PRIMARY window fwd_21d, low-borrow minus high-borrow)

| metric | value |
|---|---|
| N (rebalances) | 53 |
| gross mean spread | +0.765% |
| after-cost mean spread | +0.565% |
| t-stat | +0.64 |
| median spread | −0.223% |
| win rate (spread > 0) | 47.2% |
| IS mean (t) | −0.240% (t=−0.20, n=24) |
| OOS mean (t) | +1.231% (t=+0.98, n=29) — sign flip |
| placebo (shuffled-borrow) mean (t) | −0.740% (t=−1.68) |
| spread Sharpe | +0.12 |

Implied-carry level/dispersion (the DATA_WALL evidence — q\* ≈ borrow + dividend):
- Cross-name pooled median q\*: **−1.9 bps/yr** (≈ 0, as predicted for GC names).
- Cross-name IQR of per-name median q\*: **+69.9 bps/yr** (tiny dispersion, and
  what there is tracks dividend yield — see below).
- Per-name median q\* sorts cleanly by **dividend status**, not borrow:
  dividend payers PEP +109, TXN +100, CSCO +87, HON +85, LIN +68, QCOM +51,
  TMUS +31, AVGO +24 bps/yr are the positive tail; zero/near-zero-dividend names
  AMD −50, ISRG −48, ADBE −48, TSLA −45, NFLX −38, REGN −33, VRTX −33, META −32
  bps/yr are the negative tail. `corr(dividend_yield, q*) ≈ +0.95`. This is a
  **dividend/factor ranking**, not a persistent short-supply borrow signal — which
  is exactly why sorting on it predicts nothing (the real sort is statistically
  indistinguishable from a shuffled-borrow placebo).
- **HON is benign at +84.7 bps/yr** on the fixed foundation (a dividend payer in
  the positive tail) — the original doc's "−6857 bps pathological" was a
  split/spot-era artifact and no longer exists.
- The per-date top-minus-bottom-tercile "dispersion" of +228.8 bps/yr is the
  within-day spread of this dividend-dominated carry, not a tradeable cross-name
  borrow ranking.

> **q\* tracks dividend yield (corr +0.949).** The diagnostic
> (`scripts/diag_putcall_dividend.py`) confirms the per-name median q\* is almost
> perfectly rank-correlated with trailing dividend yield: `corr(div_yield, q*) =
> +0.949` (n=24), dividend-payer average q\* **+27.2 bps/yr** vs zero-dividend
> average **−43.8 bps/yr**. q\* is *proportional to*, not equal to, the full
> annual yield — only the dividends falling inside each option's ≤120d tenor band
> enter the parity inversion, so the implied carry is a fraction of the annual
> yield (q\* +109 bps vs PEP's +305 bps annual). The robust claim is the +0.95
> proportionality and the payer-vs-zero sign split: the "implied borrow" ranking
> *is* a dividend ranking, leaving no short-supply signal to sort on.

## Gate result (each line PASS/FAIL)

The mechanical gate verdict prints **FAIL** (the dispersion precondition now
passes, so the runner no longer auto-flags DATA_WALL), but the *honest* verdict
is still **DATA_WALL**: the dispersion that clears the floor is a dividend tilt,
not real borrow, so this universe cannot test the OR-W effect.

- PASS: cross-sectional borrow dispersion +228.8 bps/yr ≥ 100 bps floor — but this
  is **dividend dispersion**, not real borrow (q\* ≈ borrow + dividend; see above);
  the precondition is mechanically satisfied yet the measure is a factor proxy, so
  the honest verdict is DATA_WALL not a clean tradeable null.
- PASS: N=53 (≥ 30).
- **FAIL**: after-cost spread +0.565%, t=+0.64 (need > 0 AND |t| ≥ 2.0).
- **FAIL**: OOS sign stability — IS −0.240% (n=24) → OOS +1.231% (n=29), a sign
  flip; both halves are in-noise, so the flip is meaningless beyond confirming the
  null.
- PASS: placebo (shuffled-borrow) |t|=1.68 < 2.0 (null), confirming the real
  dividend-ranked sort carries no more return information than a random sort.
- Too-good tripwire: n/a (nothing is too good; the top-5 |spread| rebalances are
  market-regime moves around month-starts, e.g. 2023-01, 2024-12, 2026-04, not a
  borrow effect).

## Artifact class (if killed)

Primarily **wrong universe / DATA_WALL** (the effect is untestable on easy-to-
borrow mega-caps — analogous to T10 "small/illiquid universes" but inverted:
here we have liquidity but lack the short-constraint that creates the signal).
The implied-"borrow" *measure* carries one brain/30 artifact class:
**class 5 (confounded label)** — the parity-implied carry q\* is `borrow +
dividend yield`, and since borrow ≈ 0 here, q\* is **dividend yield wearing a
"borrow" label** (corr ~+0.95). Sorting on it is a dividend/factor tilt, not a
short-supply test. (This replaces the original doc's stale class-4 "yfinance-spot
mismatch + American early-exercise" and class-3 "HON pathological −6857 bps"
framing: the foundation now derives spot from put-call parity on the lake's own
mids, so there is no yfinance-vs-option spot mismatch, and HON's q\* is a benign
+84.7 bps/yr.) The median-aggregation defense still correctly keeps one bad pair
from defining a name, but the level bias was never a glitch — it is the dividend.

## Honest verdict (2–4 sentences)

The options-implied carry on this universe is ≈ 0 in the cross-section (pooled
median −1.9 bps/yr, IQR ~70 bps/yr), and what per-name dispersion exists is
**dividend yield, not borrow**: q\* = borrow + dividend, borrow ≈ 0, so the sort
ranks dividend payers (PEP, TXN, CSCO, HON, LIN, QCOM in the high tail) against
zero-dividend names (AMD, TSLA, NFLX, META in the low tail), corr(div, q\*) =
+0.949. Sorting names on this measure produces an after-cost fwd-21d spread of
+0.57% with t=0.64, statistically indistinguishable from a shuffled-borrow placebo
(|t|=1.68) and sign-flipping IS→OOS. This is the pre-registered DATA_WALL: the
hard-to-borrow / parity-violation effect requires hard-to-borrow names, and our
easy-to-borrow mega-caps (which, contrary to the pre-reg premise, also include
several material dividend payers) are the wrong place to test it. The kill does
**not** disprove the OR-W anomaly — it documents that this universe cannot test it,
and that on it the "implied borrow" is a dividend proxy.

## Files

- `src/trader/catalysts/putcall_parity_borrow.py` — pure parity math + cross-
  sectional sort + gate (reuses the `vol_surface_data` loader/BS core)
- `tests/financial/test_putcall_parity_borrow.py` — 23 network-free tests
- `scripts/run_putcall_parity_borrow_study.py` — end-to-end runner
- `scripts/diag_putcall_dividend.py` — mechanism diagnostic: q\* vs dividend
  yield (corr +0.949, payer avg q\* +27.2 vs zero-div −43.8 bps/yr)
- `research/putcall_parity_borrow_report.md` — raw run output
- `data/putcall_parity_borrow_results.txt` — raw run output (copy)
- `output/catalysts/putcall_parity_borrow_study.json` — machine-readable summary

## Registry status update line (paste into brain/34)

`- ⛔ **T26** Hard-to-borrow / put-call-parity violations — *DATA_WALL: easy-to-borrow mega-cap universe → implied carry q* ≈ 0 (cross-name pooled median −1.9 bps/yr, IQR ~70 bps/yr). MECHANISM (corrected): q* = borrow + dividend, and since borrow ≈ 0 here, q* IS dividend yield — corr(div_yield, q*) = +0.949 (payer avg q* +27.2 vs zero-div −43.8 bps; payers PEP +109/TXN +100/CSCO +87/HON +85 bps vs zero-div AMD −50/TSLA −45/NFLX −38 bps), a factor tilt not short-supply pricing. Cross-sectional low-minus-high fwd-21d spread +0.57% after-cost, t=+0.64 (N=53), ≈ shuffled-borrow placebo (|t|=1.68), IS→OOS sign flip. Re-run on parity-anchored-spot foundation (commit bdc1174): the prior doc's "yfinance-spot mismatch / American-exercise / HON −6857 pathological" framing is stale — spot is parity-derived and HON q* is a benign +84.7 bps. Several universe names pay material dividends, contradicting the pre-reg's "~0-dividend" premise. OR-W HTB needs hard-to-borrow small/short-squeeze names we don't have — wrong universe, cleanly documented.*`
