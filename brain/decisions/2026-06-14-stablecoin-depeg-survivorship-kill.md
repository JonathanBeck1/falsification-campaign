# Decision: Stablecoin Depeg Mean-Reversion (T34)

Pre-registration: `research/stablecoin_depeg_preregistration.md`. Falsify-first.
Raw run: `data/stablecoin_depeg_results.txt`.

## Verdict

### ❌ KILL — a textbook survivorship/tail trap: one corpse (UST −67.6%) flips a pretty survivor-only +3.1% into a full-sample −16.0%

The naive "buy any stablecoin below $0.98, hold 30d for the re-peg" rule looks
like free money **only if you delete the coins that died**. Include the deaths
and the strategy is short-vol with a fatal left tail. N is also far too small to
claim anything (4 events). Both the small-N gate and the survivorship gate fail.

## Numbers (after-cost 20 bps, PRIMARY window = ret_30d, daily close)

| metric | WITH dead coins (honest) | SURVIVOR-ONLY (the illusion) |
|---|---|---|
| N | 4 | 2 |
| mean | **−16.01%** | **+3.13%** |
| median | −0.20% | +3.13% |
| t-stat | −0.93 | +3.74 |
| min | −67.60% (UST) | +2.30% |
| win rate | 50% | 100% |
| skew | −1.13 | 0.00 |

- **Survivorship effect (with − without) = −19.14%.** Deleting UST/USTC is the
  entire difference between a "great" trade and a losing one.
- **Tail domination:** drop the single worst event (UST −67.6%) → mean flips to
  **+1.19%**. One of four events controls the sign. (`worst_share` = 1.06: the
  worst event is *more* than 100% of the summed return — the rest net positive.)
- IS (pre-2023): N=1, the lone UST death, −67.6%. OOS (2023+): N=3, +1.19%,
  t=+0.59 — not significant, and only positive because the deaths are pre-2023.
- Placebo (random non-event entries, same coins): mean −0.21% median, t=−3.64,
  with its own fat tail (USTC's post-death noise) — i.e. even random entries on
  this universe carry the same steamroller risk; the depeg signal does not beat
  it.

## Event ledger (all 4, deaths included by design)

| symbol | t0 | entry | ret_30d | recovered | note |
|---|---|---|---|---|---|
| USTUSDT | 2022-05-09 | 0.7540 | **−67.40%** | no | TerraUST death; archive ends 2022-05-13 at ~$0.18 — terminal loss REALIZED |
| USTCUSDT | 2023-03-10 | 0.0221 | −2.50% | no | Terra Classic (already dead); depeg is noise around its ~$0.02 floor |
| TUSDUSDT | 2024-02-16 | 0.9774 | +2.50% | yes | survivor re-peg |
| USDCUSDT | 2023-03-11 | 0.9592 | +4.17% | yes | SVB scare; daily close (intraday low ~$0.88 was deeper) re-pegged |

## Gate result

- **FAIL: N = 4** (need ≥ 30). Major-stablecoin daily depegs are rare; the
  small-N verdict was pre-registered as the likely (and acceptable) outcome.
- **FAIL: after-cost mean WITH dead = −16.01%, t = −0.93** (need > 0 & |t| ≥ 2).
- **FAIL (artifact): survivor-only +3.13% but with-dead −16.01%** — including the
  corpses flips the sign. This is the pre-registered survivorship kill.
- **FAIL: tail dominates** — removing UST flips the sign (−16.01% → +1.19%).
- too-good tripwire: survivor-only win rate = 100% / t=3.74 — exactly the
  short-vol red flag the pre-reg warned about (wins often, one loss is fatal).

## Artifact class (brain/30)

Primarily **survivorship bias** (the crypto analogue of the small/illiquid-equity
and CEF-survival kills, T10/T16): the live/surviving universe omits the names
that went to zero, and those are precisely the ones the strategy is long into the
abyss. Secondarily **tail-domination / short-vol mislabeling**: a negatively-
skewed P&L (many small +0.x% re-peg wins funded by rare ~−70% to −100% deaths)
whose mean is set by one event — reporting only the mean (or worse, the median,
+0.0% to −0.2%) hides that the strategy sells a credit/solvency option for pennies.

## Honest verdict (skeptical read)

This is "picking up pennies in front of a steamroller," and the steamroller
(UST) is right there in the sample. The survivor-only number (+3.1%, t=3.74,
100% win) is seductive and exactly what a naive backtest on Binance's *live*
stablecoin list would report — which is the trap. Once you include the one major
USD stablecoin that actually died, the after-cost mean is −16% and statistically
indistinguishable from a loss; the entire sign is set by a single event.

What this KILL does NOT prove: it does not prove no stablecoin re-peg trade
exists at finer resolution (intraday, where USDC's ~$0.88 low gave a much deeper
entry than the $0.96 daily close), nor with an active solvency screen that would
have refused to buy UST as Anchor's reserves bled. It proves the **naive,
unscreened daily "buy any depeg" rule is a survivorship/tail artifact** — and
that any future variant must (a) be solvency-conditioned and (b) carry the dead
coins in its sample by construction. N=4 also means even the survivor side is
anecdote, not evidence. Also note USTC's −2.5% is itself a curiosity: a coin that
already died still "depegs" forever around its floor, generating perpetual fake
signals — another reason the naive rule self-destructs.

## Data-quality finding (fixed in this work)

While running, I caught a real provenance bug in the shared crypto data layer:
Binance's `data.binance.vision` archive switched kline `open_time` from
**milliseconds to microseconds** starting ~2025-01. The hardcoded `unit="ms"` in
`parse_kline_csv` mapped those 16-digit microsecond stamps to the year ~52,000,
which pandas wrapped into 1970 — silently corrupting every 2025-2026 bar (every
symbol's span showed `1970-01-01..2024-12-31`). Fixed via a magnitude-based
`_epoch_to_utc(s/ms/us)` auto-detector applied to both kline and funding parses,
with regression tests. This bug also affected the funding-carry foundation
(T29's 2025+ tail), now corrected. (Artifact class 4: derived/fake-data
provenance — caught and fixed before it could flatter anything.)

## Files

- `src/trader/catalysts/stablecoin_depeg.py` — pure core (event detection with
  re-arm, terminal-death realization, survivorship split, tail/skew, gate)
- `src/trader/catalysts/crypto_data.py` — added spot-kline fetch + the
  ms/us epoch auto-detect fix (reuses the existing pure parse core)
- `tests/financial/test_stablecoin_depeg.py` — 17 network-free tests
- `tests/financial/test_crypto_data.py` — +2 microsecond-epoch regression tests
- `scripts/run_stablecoin_depeg_study.py` — end-to-end runner (free data)
- `data/stablecoin_depeg_results.txt` — raw run output

## Registry status update line (paste into brain/34)

`- ❌ **T34** stablecoin depeg mean-reversion — *survivorship/tail trap: survivor-only +3.1% (t=3.74, 100% win) flips to −16.0% once UST's −67.6% death is included; drop-worst flips sign; N=4. Plus a real ms→µs epoch data-bug fix in crypto_data.*`
