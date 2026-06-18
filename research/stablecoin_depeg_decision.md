# Decision: Stablecoin Depeg Mean-Reversion (T34)

Pre-registration: `research/stablecoin_depeg_preregistration.md`.
Full decision record: `brain/decisions/2026-06-14-stablecoin-depeg-survivorship-kill.md`.
Raw run: `data/stablecoin_depeg_results.txt`.

## Verdict

### ❌ KILL — survivorship/tail trap; one corpse (UST −67.6%) flips survivor-only +3.1% into full-sample −16.0%

## Numbers (after-cost 20 bps, PRIMARY = ret_30d, daily close)

| metric | value |
|---|---|
| N (usable depeg events) | 4 |
| after-cost mean WITH dead coins | **−16.01%** |
| after-cost mean SURVIVOR-ONLY | **+3.13%** |
| survivorship effect (with − without) | **−19.14%** |
| t-stat (with dead) | −0.93 |
| t-stat (survivor-only) | +3.74 (the trap) |
| drop-worst (remove UST) mean | +1.19% (sign flip) |
| IS mean (t) | −67.60% (N=1, the UST death) |
| OOS mean (t) | +1.19% (t=+0.59, N=3) |
| placebo mean | −0.21% median, t=−3.64 |

## Gate result (each line PASS/FAIL)

- FAIL: N=4 (need ≥ 30) — major-stablecoin daily depegs are rare; small-N was
  the pre-registered likely outcome.
- FAIL: after-cost mean WITH dead = −16.01%, t=−0.93 (need > 0 & |t| ≥ 2).
- FAIL (artifact): survivor-only +3.13% but with-dead −16.01% — corpses flip the
  sign. The pre-registered survivorship kill.
- FAIL: tail dominates — removing UST flips −16.01% → +1.19%.
- too-good tripwire TRIGGERED: survivor-only 100% win / t=3.74 — the short-vol
  red flag itself.

## Artifact class (brain/30)

Survivorship bias (crypto analogue of T10/T16) + tail-domination / short-vol
mislabeling. A secondary, separately-fixed **data-provenance** finding: Binance
switched kline `open_time` from ms to µs in 2025; the old hardcoded `unit="ms"`
corrupted all 2025-2026 bars (showed as 1970). Fixed with an auto-detecting
`_epoch_to_utc` + regression tests; also corrects T29's 2025+ tail.

## Honest verdict

Textbook "pennies in front of a steamroller," and the steamroller (UST) is in
the sample. The seductive survivor-only +3.1%/100%-win is exactly what a naive
backtest on Binance's *live* stablecoin list reports — and is the trap. Include
the one major USD stablecoin that died and the after-cost mean is −16% with the
sign set by a single event. Kill does NOT prove no re-peg trade exists at
intraday resolution or with a solvency screen; it proves the naive, unscreened
daily "buy any depeg" rule is a survivorship/tail artifact. N=4 ⇒ anecdote.

## Files

- `src/trader/catalysts/stablecoin_depeg.py` — pure core + gate
- `src/trader/catalysts/crypto_data.py` — spot fetch + ms/µs epoch fix
- `tests/financial/test_stablecoin_depeg.py` — 17 network-free tests
- `tests/financial/test_crypto_data.py` — +2 µs-epoch regression tests
- `scripts/run_stablecoin_depeg_study.py` — end-to-end runner
- `data/stablecoin_depeg_results.txt` — raw run output
