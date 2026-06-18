# Decision: Single-name 25-delta skew dynamics (T25)

Pre-registration: `research/vol_skew_preregistration.md`. Falsify-first.
Raw output: `data/vol_skew_results.txt`. Slug: `vol_skew`.

> **Re-run note (2026-06-17) — canonical numbers.** After the `risk_reversal_25d`
> delta-tolerance-band fix (drops ~27 off-band thin-wing dates), T25 was re-run.
> The figures in the body below are the earlier run and are **superseded**; the
> verdict (KILL) and every sign/mechanism are unchanged. Canonical headline
> numbers (matching `brain/34`, the scoreboard, and `PAPER_DRAFT.md` §7.5):
> PRIMARY long–short after-cost **t = −0.10**, IS **+0.12%** → OOS **−0.24%**
> SIGN-FLIP, placebo **p = 0.89**, premium residual α **t = −33.50** on
> **5,197 rows** (N = 219 weekly / 24 names). Source: `data/vol_skew_results.txt`.

## Verdict

### ❌ KILL — skew neither predicts returns (signal) nor pays a distinct premium (it is short-vol + short-delta beta in disguise)

Both pre-registered framings fail. The PRIMARY (signal) long–short is pure noise
that sign-flips out of sample and is statistically indistinguishable from its own
within-date placebo. The SECONDARY (premium) framing is fully explained by
short-volatility + short-delta beta — the KEY control's residual alpha is
wrong-signed with enormous |t|, and the short-put proxy carries the ordinary
short-crash-insurance drawdown its mechanism implies.

> **Provenance note (foundation re-run).** These numbers were re-generated on the
> parity-anchored-spot foundation (`vol_surface_data.py`, fix commit
> `bdc1174`), which derives the per-snapshot underlying by inverting put-call
> parity rather than reading a split-adjusted yfinance close. The verdict is
> unchanged from the original run, but the original supporting numbers were
> contaminated by the split/spot bug — most visibly a **fabricated** "worst
> snapshot −319% / cumulative drawdown −205 vol-units" that is impossible for a
> 21-day cash-equity forward return (it cannot fall below −100%). Those figures
> are removed here and replaced with the reproducible fixed-foundation values
> (worst proxy payout ≈ −0.48, cumulative drawdown ≈ −75.7). The KILL is cleaner,
> not weaker.

## Universe (explicit)

24 fully-collected single names, 2022-01-03 .. 2026-05-11, weekly cadence:
ADBE AMAT AMD AVGO BKNG COST CSCO GOOG GOOGL HON INTU ISRG LIN LRCX META MU NFLX
PEP QCOM REGN TMUS TSLA TXN VRTX. **AAPL, AMZN, NVDA EXCLUDED** (still
collecting). QQQ/SPY used only conceptually as the market control; the
long–short is cross-sectionally demeaned, so the universe baseline is netted out
by construction. Panel: **5,224 (name, weekly-date) rows over 413 dates**; the
PRIMARY t-stat is on the **219** weekly long–short observations. The 25Δ skew is
positive 90.7% of the time (median +3.37 vol-pts) — the normal equity
crash-skew shape is present in the data, so the foundation is reading real skew.

## Numbers (after-cost, PRIMARY window fwd_ret_0_p21)

| metric | value |
|---|---|
| N (weekly long–short obs) | 219 |
| gross mean | +0.073%/period (t=+0.14) |
| after-cost mean (10 bps) | **−0.027%/period (t=−0.05)** |
| after-cost mean (20 bps, 2×) | −0.127% (t=−0.25) |
| IS mean (t), n | +0.202% (t=+0.40), n=113 |
| OOS mean (t), n | **−0.271% (t=−0.30), n=106 — SIGN FLIP** |
| placebo (200-perm skew-shuffle) | obs +0.073% vs perm −0.036%; **p=0.845** |
| Δ20d-skew variant (net) | −0.023% (t=−0.05) — also null |

## Gate result (PRIMARY signal — each line)

- **PASS** N: 219 ≥ 30 ✓ (this one passes; listed for completeness).
- **FAIL** after-cost |t|=0.05 < 2.0.
- **FAIL** OOS sign stability: IS +0.00202 → OOS −0.00271 (sign flip; both halves N≥10).
- **PASS-as-designed** pooled baseline: long–short is demeaned; up/down symmetry
  sum = 0.00000 (antisymmetric, so no inherited drift to remove).
- **FAIL** placebo: within-date skew-shuffle perm p=0.845 (the observed long–short
  is an entirely ordinary draw from the shuffle null — even *more* indistinct than
  the contaminated run's p=0.33).
- Too-good tripwire: not triggered (Sharpe −0.03, nothing to inspect).

Any one of {|t|<2, OOS flip, placebo p≥0.05} is a pre-registered kill; all three fire.

## Premium framing (SECONDARY) + the KEY disguise control

- Short-25Δ-put proxy P&L (vol-pts), 2 vol-pt cost: mean **−0.0144 (t=−16.47)**,
  win 45.8%, **worst single payout −0.4769** (the put seller's worst single-snapshot
  insurance payout, a benign ~−48% drawdown leg), **cumulative max drawdown
  −75.7 vol-units**; at 4 vol-pt cost mean −0.0344 (t=−39.30). The proxy charges the
  realized downside as the insurance payout, so it is tail-honest; the sign is
  negative and the cumulative book bleeds, as a short-crash-insurance proxy must.
  *(There is no −319% / −205 vol-unit tail — that was a split/spot artifact; a
  cash-equity 21d forward return is bounded below by −100%.)*
- **Drop-worst-month:** removing the worst month (2024-07) barely moves it
  (−0.01443 → −0.01305, t −16.47 → −15.07), i.e. the loss is pervasive, not one
  month — there is no "ex one selloff it's fine" rescue.
- **KEY CONTROL (the disguise test):** regress premium P&L on short-ATM-vol +
  short-delta-beta. Result: **residual alpha = −0.0546, t=−33.56**,
  beta_vol=+0.126, beta_mkt=+0.377, R²=0.468. The premium loads positively on
  both the short-vol leg and the market-beta leg, and the residual is
  wrong-signed with enormous |t| — there is **no positive distinct skew premium**
  after stripping short-vol + short-delta. The "skew premium" is short-vol +
  short-delta beta in disguise, exactly the pre-registered failure mode.

## Artifact class (brain/30)

**Friction-scale noise + decayed/in-noise effect** for the signal framing (a
weak in-sample tilt t=+0.40 that does not clear cost and sign-flips OOS, fully
indistinct from its within-date placebo at p=0.85), and **"premium = disguised
beta"** for the harvest framing — the same disguised-short-vol/short-delta lesson
as the equity VRP kill (T19, mechanism-null) and the levered-beta crypto-momentum
kill (T33). The proxy book's negative carry and ~−75.7 cumulative drawdown are the
ordinary left-tail bleed these short-crash-insurance trades always carry — *not*
the impossible −319%/−205-vol-unit catastrophe the contaminated (split/spot) run
reported.

## Honest verdict (2–4 sentences)

The 25-delta crash skew is genuinely present and large in single-name options
(positive 90.7% of the time, median +3.37 vol-pts), but neither its level nor its
20-day change predicts subsequent 21-day stock returns after cost: the
cross-sectional long–short is −0.03%/period at t=−0.05, flips sign out of sample,
and does not beat a within-date placebo (p=0.85). Selling the expensive downside
earns no distinct premium once short-vol and short-delta beta are removed (residual
alpha t=−33.56, wrong sign), and the proxy book carries the ordinary
short-crash-insurance bleed the skew is insuring against (worst single payout
−0.48, cumulative drawdown −75.7 vol-units). This kill does NOT prove skew is uninformative at finer cadence
(0DTE/intraday), at a different tenor/delta, or conditioned on events
(earnings/high-VIX); it tests the unconditioned weekly EOD cross-section of the
30-day 25Δ skew across 24 liquid large-caps, after realistic cost, and finds no
survivable edge.

## Data-wall / robustness note (split & spot — now FIXED at the foundation)

The campaign memory flagged a split/spot wall (yfinance split-adjusted closes
mismatching the lake's unadjusted strikes for AVGO/NFLX). This is now **fixed at
the foundation**: `vol_surface_data.py` (commit `bdc1174`) derives each snapshot's
underlying by **inverting put-call parity** on the lake's own matched call/put
mids (`S ≈ K·e^{-rT} + (C−P)`), so the moneyness anchor is on the *same
unadjusted scale as the strikes* and never reaches for a split-adjusted yfinance
close. Effect on this study: (1) the IV/skew read is on a provenance-clean,
in-scale spot; the panel grows from 4,493 → **5,224** usable rows and the skew is
positive **90.7%** of days (median **+3.37 vol-pts**) — a slightly cleaner read of
the same real crash-skew shape; (2) the short-put proxy's payout leg uses the
forward *equity* return, which is bounded below by −100%, so the **fabricated
−319% worst snapshot / −205-vol-unit cumulative drawdown of the contaminated run
are gone** — the true worst single payout is −0.4769 and cumulative drawdown
−75.7. The forward-return yfinance series remains split-continuous (no $1700→$170
cliff), so no spurious −90% returns enter the panel. The KILL is structural and
*strengthens* under the fix: the PRIMARY long–short t moves from a contaminated
+0.50 to −0.05, the placebo p from 0.33 to 0.85, and the premium residual alpha
from −19.58 to −33.56 (on 5,224 rows) — every gate check fails more decisively,
none more weakly.

## Files

- `src/trader/catalysts/vol_skew.py` — PURE core + gate (long–short, placebo,
  IS/OOS, up/down symmetry, short-put premium proxy, disguise OLS, tail).
- `src/trader/catalysts/vol_surface_data.py` — REUSED foundation (loader, BS IV
  solver, `risk_reversal_25d`/`atm_iv`). Not modified by this study; the
  parity-anchored-spot fix (commit `bdc1174`) is upstream of this re-run.
- `tests/financial/test_vol_skew.py` — network-free unit tests (all pass on the
  fixed foundation).
- `scripts/run_vol_skew_study.py` — end-to-end live runner.
- `data/vol_skew_results.txt` — raw run output.
- `research/vol_skew_preregistration.md` — pre-registration (written first).

## Registry status update line (paste into brain/34)

`- ✅ **T25** Single-name 25Δ skew dynamics — *KILL: skew real & large (median +3.37 vol-pts, +90.7% of days) but signal-null — tertile long–short (long low-skew/short high-skew) net −0.03%/wk t=−0.05, IS +0.20% → OOS SIGN-FLIP −0.27%, placebo p=0.85; Δ20d variant null too. Premium framing = short-vol+short-delta beta in disguise: residual alpha after the two-leg control is WRONG-SIGNED t=−33.56 (β_vol+0.13, β_mkt+0.38, R²0.47), short-put proxy bleeds (worst single payout −0.48, cum DD −75.7 vol-units, drop-worst-month no rescue). N=219 weekly obs / 5,224 rows / 24 names 2022–2026. Re-run on parity-anchored-spot foundation (commit bdc1174); the prior run's "−319%/−205-vol-unit tail" was a split/spot artifact (now removed). Friction-scale noise + disguised-beta; same lesson as VRP T19.*`
