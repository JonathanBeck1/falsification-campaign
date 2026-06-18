# Decision: Crypto Volatility Risk Premium — Deribit DVOL (T32)

Date: 2026-06-14
Pre-registration: `research/crypto_vrp_preregistration.md` (signed BEFORE any
number was computed). Falsify-first. Crypto analog of the equity-VRP kill
(`brain/decisions/2026-06-13-vrp-qqq-in-sample-kill.md`).
Raw run: trades-repo `data/crypto_vrp_results.txt`.

## Verdict

### ⚠️ SPLIT — BTC mechanically PASSES the pre-registered gate but is DECAYING; ETH is a clean KILL. Net: NOT carried forward as a live edge.

A real, mechanism-confirmed crypto VRP exists in BTC and clears every
pre-registered gate **including the full tail** — unlike the equity QQQ VRP,
which failed at the mechanism level (corr 0.01). But the BTC edge is **decaying
out** (IS Sharpe 3.0 → OOS t=1.88 → most-recent-18-months t=1.0), ETH fails OOS
sign stability and after-cost significance outright, and the whole thing rests
on a **variance-swap-replication proxy**, not a real Deribit options book with
margin. The honest posture: the crypto VRP is real but is being arbitraged away,
the opposite of the "younger, less-arbitraged market preserves it" thesis. We do
NOT promote it to a live strategy on a decaying single-name proxy edge.

## Was the data fetchable?

**Yes.** Deribit's public REST `get_volatility_index_data` (DVOL, the BTC/ETH
30-day implied-vol index) is reachable from this environment, paginated, free,
no key. **Data wall:** DVOL history begins **2021-03-24** for both currencies
(the index did not exist earlier), so the canonical **2020-03 COVID crypto
crash is OUT of sample**. The IS window still contains 2021-05, LUNA/UST
(2022-05), and FTX (2022-11). Spot RV from the Binance `data.binance.vision`
archive (same survivorship-honest source as T29/T33). 1,909 DVOL days each.

## Numbers (after-cost, PRIMARY = daily short-vol proxy, TAIL-INCLUSIVE)

| metric | BTC | ETH |
|---|---:|---:|
| mean IV − fwd-RV spread (existence) | **+8.87 vol-pts** (IV>RV 73%) | +4.67 vol-pts (IV>RV 65%) |
| N (days) | 1894 | 1894 |
| short-vol net mean/day (vega units) | **+0.0610** | +0.0172 |
| t-stat | **+5.10** | +0.93 |
| net Sharpe (ann) | +2.24 | +0.41 |
| **mechanism corr(spread, pnl)** | **+0.181** | +0.175 |
| quartile gradient monotone? | **yes** [-0.06,0.02,0.10,0.18] | yes [-0.20,-0.03,0.10,0.19] |
| IS mean (t) | +0.0879 (t=5.02) | +0.0529 (t=2.11) |
| OOS mean (t) | +0.0300 (t=1.88) | **−0.0237 (t=−0.86)** |
| worst single day | −7.56 (2026-02-05) | −14.15 (2021-05) |
| max drawdown (cum vol-pts) | −13.34 | −41.28 |
| net @2× cost (4 vol-pt) | +0.0510 (t=4.26) | +0.0072 (t=0.39) |
| random-entry placebo (t) | +0.0097 (t=0.55) | −0.0603 (t=−2.05) |

## Gate result (each line PASS/FAIL)

**BTC — PASS (all):**
- PASS N=1894 (≥30).
- PASS after-cost mean +0.0610, t=+5.10 (TAIL-INCLUSIVE).
- PASS OOS sign stable (IS +0.0879, OOS +0.0300, both n≥10, same sign).
- PASS MECHANISM corr +0.181 ≥ 0.10 AND monotone quartile gradient — the
  non-sign-only mechanism gate the equity kill taught us to require. This is the
  decisive contrast: crypto VRP P&L genuinely tracks the IV−RV spread.
- PASS TAIL — verdict does NOT hinge on dropping the worst month (drop-worst-3
  still t=6.56); worst day −7.56, maxdd −13.3.
- PASS placebo (random-entry ~0, t=0.55).

**ETH — FAIL (KILL):**
- FAIL after-cost t=0.93 (<2).
- FAIL OOS sign flip (IS +0.0529 → OOS −0.0237).
- (Mechanism + tail + placebo individually PASS, but two binding gates fail.)

## The skeptical read — show the tail and the decay

The instruction was: "crypto VRP looks great until the vol spike that eats it;
show the tail." It does, and the proxy honestly eats it. The worst BTC days map
1:1 onto real catastrophes — **2022-11-09 (FTX, −5.20)**, 2022-06-13 (3AC/Celsius),
**2022-05-09 (LUNA/UST, −3.77)**, 2021-05-12 (May crash), 2026-02-05 (−7.56). The
edge SURVIVES these *because* DVOL was already pricing 70–110 vol going into them
(the insurance demand was visibly rich), so the short collected enough premium in
the calm to absorb the spikes. That is the VRP mechanism working as advertised —
and the +0.18 spread↔pnl correlation + monotone quartile gradient confirm the P&L
is the premium, not just short-gamma beta.

**But the deeper finding is decay, not the tail.** BTC IS (2021-03..2023-12)
Sharpe 3.01 / t=5.02; OOS (2024+) t=1.88; **2025-01-onward t=1.00, basically
flat.** The premium was fat in the 2021–2023 high-vol regime and has compressed
as crypto vol markets matured and vol-sellers arrived — the *reverse* of the
pre-registered "young, retail-heavy, less-arbitraged ⇒ premium persists"
hypothesis. The full-sample BTC pass is carried by the early high-VRP era. ETH,
the less-liquid name, has *already* decayed past the kill line.

## Artifact class (for the parts that fail)

Not an artifact in the brain/30 taxonomy sense — the spread and its mechanism are
real (corr ≠ 0, monotone gradient, tail-inclusive). The ETH kill and the BTC
caveat are **decayed/regime-dependent effect**: a genuine historical premium that
is compressing toward noise as the market arbitrages it, plus **proxy risk**
(variance-swap replication, not a margined options book — real Deribit
execution, wing slippage, and margin calls on a spike would erode the modest
remaining edge further).

## Honest verdict (2–4 sentences)

Crypto IV systematically exceeds realized vol (BTC +8.9, ETH +4.7 vol-pts, IV>RV
65–73% of days) and a short-vol proxy that harvests it earns a real,
mechanism-confirmed, tail-surviving return in BTC — a materially better outcome
than the mechanism-null equity QQQ VRP. **But it is decaying** (BTC OOS t falls
to ~1, recent-18-mo flat) and ETH already fails OOS, so on a decaying single-name
proxy edge we do NOT promote it to a live strategy. This kill/caveat does NOT
prove crypto VRP never existed (it clearly did, richly, in 2021–2023) — it shows
the harvestable, after-cost, tail-paid premium is compressing toward noise and
that any live attempt would need a real margined options book and a conditioned
(regime/level-gated) entry under a fresh pre-registration, on data that includes
a COVID-class spike the DVOL history cannot reach.

## Deviations from pre-registration

- None material. The pre-reg fixed BTC+ETH, the DVOL source, the variance-swap
  proxy, 2-vol-pt friction, IS/OOS at 2024-01-01, and the non-sign-only
  mechanism gate (corr ≥ 0.10 + monotone quartiles) — all applied as written.
- The pre-reg anticipated the 2020-03 data wall and the proxy limitation in §9;
  both materialized exactly. No specification was changed after seeing results.

## Files

- `research/crypto_vrp_preregistration.md` — signed pre-registration
- `src/trader/catalysts/crypto_vrp.py` — pure core + gate
- `src/trader/catalysts/crypto_vrp_data.py` — Deribit DVOL fetch (injectable seam)
- `tests/financial/test_crypto_vrp.py` — 21 network-free tests
- `scripts/run_crypto_vrp_study.py` — end-to-end runner
- `data/crypto_vrp_results.txt` — raw run output

## Registry status update line (paste into brain/34 — main thread owns the file)

`- ⚠️ **T32** Crypto VRP (Deribit DVOL, BTC/ETH) — *real mechanism-confirmed premium (BTC corr +0.18, monotone gradient, tail-survived) UNLIKE equity QQQ; but DECAYING (BTC OOS t=1.88, recent-18mo flat) + ETH OOS sign-flip KILL. Not promoted: decaying single-name proxy edge, no live options book, 2020-03 spike out of sample. Data fetchable; wall = DVOL inception 2021-03-24.*`
