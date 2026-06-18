# Pre-Registration: Single-Name Earnings IV Crush (T23)

> Status: pre-registered design, written **before** computing or inspecting any
> P&L. Hypothesis, sample, windows, split, gate, and kill criteria are fixed
> here so a favorable specification cannot be selected after the fact.
>
> Standard campaign template (`brain/34_master_test_registry.md`, universal gate
> in `brain/30_campaign_findings.md`). Foundation reused:
> `src/trader/catalysts/vol_surface_data.py` (EOD option lake loader + pure
> Black-Scholes IV solver).

## 1. Hypothesis (one sentence, directional, falsifiable)

Selling a single name's ~ATM straddle at the close the session **before** its
scheduled earnings and buying it back at the close the session **after** earns a
positive after-cost P&L, because pre-earnings ATM IV systematically **overstates**
the realized overnight earnings move (the implied straddle price exceeds the
realized |move| on average).

## 2. Mechanism — why would this be inefficient?

Event-vol risk premium. The buyer of pre-earnings options wants protection /
leverage across a known binary; option *sellers* demand a premium for bearing the
gap risk, and on average the realized move comes in below the priced move. The
forced/uninformed counterparty is the directional speculator and the hedger who
will overpay for convexity into a scheduled catalyst. The friction that stops it
being trivially arbed away is the **tail**: single-name earnings produce
occasional 20–30% gaps (NFLX -35% Apr-2022, META -25% Oct-2022) that hand the
straddle seller a catastrophic loss; a handful of these can erase many small
crush wins. Single-name option spreads are also wide (5–15%+ of mid), so the
gross premium must clear a large friction bar.

**Honest prior:** marginal-to-null after cost. The IV-crush phenomenon (implied
> realized into earnings) is real and well documented, but it is a
**compensation for jump variance**, not free alpha; the campaign's prior is that
once we (a) price the wide single-name spread honestly and (b) let the fat left
tail land in-sample, the after-cost expectancy collapses toward zero or negative.
This is the same posture that killed T19 (VRP) and is the explicit lesson from
T43 (announcement premium = compensated variance, corr(|CAR|, vol) high).

## 3. Data + provenance

- **Universe (fixed, 24 single names — stated explicitly):**
  ADBE AMAT AMD AVGO BKNG COST CSCO GOOG GOOGL HON INTU ISRG LIN LRCX META MU
  NFLX PEP QCOM REGN TMUS TSLA TXN VRTX.
  **EXCLUDED** AAPL, AMZN, NVDA — their EOD option lake is still being collected
  and is incomplete; including a partially-collected name would bias coverage.
  Index ETFs (QQQ, SPY) are not single-name earnings names and are excluded.
- **Option source:** owned EOD option-chain parquet lake at
  `$TRADER_EOD_LAKE_ROOT/root=TICKER/...`,
  ThetaData-collected, ~1115 trade-days/name, 2022..2026. Columns: trade_date,
  expiration, strike, right, bid, ask, close, volume, open_interest,
  underlying_close (NULL across the lake), source.
- **Option price:** mid = (bid+ask)/2; rows with bid<=0, ask<=0, or mid<=0 are
  dropped (a one-sided/stale quote is not a price). Loaded via the audited
  foundation `load_option_quotes`.
- **Spot anchor — PROVENANCE FIX (decided at pre-reg, before results):** the
  lake's `underlying_close` is NULL, and the foundation's yfinance fallback
  returns **split-adjusted** closes that do NOT match the lake's
  *as-of-trade-date* (unadjusted) strikes for names that split after the trade
  date (verified: AVGO 10:1 Jul-2024 and the NFLX series both come back ~10x
  wrong, putting "ATM" on a deep-ITM strike and producing absurd IVs of 290%
  collapsing to 1%). We therefore anchor spot from the option chain itself via
  **put-call parity** on the front expiration: S ≈ K* + (C(K*) − P(K*)) at the
  strike K* where |C−P| is minimised (verified: recovers NFLX = $326.44 on
  2023-01-18, consistent with the strikes). Parity spot uses only the lake's own
  quotes — no external, split-mismatched series. Strike/right closest to that
  spot defines ATM. This is the honest, self-consistent provenance for a strikes-
  based test and is fixed here.
- **Earnings dates:** yfinance `Ticker(t).get_earnings_dates(limit=...)`,
  filtered to 2022..2026 (the lake span). AMC vs BMO inferred from the ET
  timestamp hour (>=13:00 ET => AMC, priced next session; midnight/missing =>
  AMC). Earnings calendars are **knowable ex-ante** — the date is published
  weeks ahead — so trading the close before is causal, not look-ahead.
- **Sample span:** IS = earnings year ∈ {2022, 2023}; OOS = {2024, 2025, 2026}.

## 4. Cohort & "control" definition

- **Event (treated):** one scheduled earnings announcement of a universe name
  with (a) a tradeable front-expiration straddle on the pre-earnings close, and
  (b) a post-earnings close mark on the same options. Pre-earnings close = the
  last lake trade_date strictly before the session that prices the release;
  post-earnings close = the first lake trade_date on/after that session.
- **Front expiration:** the nearest expiration with >= 5 calendar days to expiry
  on the pre-earnings close (avoids same-day 0-DTE pin artifacts) AND that still
  exists in the post-earnings shard (so we can mark the exit). The straddle is
  the call+put at the ATM strike (parity-spot-nearest).
- **The KEY honest control (lesson from T43):** is any premium just compensation
  for jump variance rather than alpha? Two pre-registered checks:
  1. **Implied-vs-realized decomposition.** Per event compute the *priced move*
     = ATM straddle mid / spot (the breakeven the seller is paid for) and the
     *realized move* = |post_spot/pre_spot − 1|. The crush premium is
     priced_move − realized_move. If positive on average, IV overstated the move.
  2. **Jump-variance correlation.** Corr(short-straddle P&L, realized move) must
     be strongly negative (the deaths are the big moves), and we report whether
     the *mean* premium survives after the tail lands — i.e. report the premium
     net of the variance it is compensating, not just the raw mean.
- **Pooled baseline / placebo:** a **non-earnings placebo** — run the identical
  "sell front straddle at close, buy back next session" round trip on randomly
  sampled NON-earnings dates of the same names (same tenor filter, same costing).
  The placebo isolates the *earnings-specific* crush from the ordinary one-day
  theta/vol carry of selling a straddle. The earnings premium must exceed the
  placebo (Welch t), else the "edge" is just being short one day of vol generally.

## 5. Measurement window + LOOK-AHEAD statement

- **Hold window (event time):** enter at pre-earnings close, exit at the first
  post-earnings close (1 overnight hold spanning the announcement). PRIMARY P&L
  metric = after-cost short-straddle return as a fraction of spot (so events are
  comparable across price levels). Secondary (reported, non-gating): the
  priced-vs-realized move gap; the per-$ premium.
- **Look-ahead audit:** the earnings DATE is published ex-ante (yfinance
  calendar reflects the scheduled date), so entering at the prior close is
  causal — no future information defines the entry. The AMC/BMO flag uses only
  the announcement timestamp, known at entry. Spot anchoring uses only quotes
  observable on each respective close. The realized move and exit mark use only
  post-earnings-close data, strictly after entry. No measurement input precedes
  its observation.

## 6. Friction model

- **Single-name options are WIDE.** We do NOT assume a fixed bps cost. We cross
  the actual quoted spread: enter (sell) at **bid**, exit (buy back) at **ask**
  on each leg, using the lake's own bid/ask. That is the honest fill for a
  liquidity taker and already embeds the full round-trip spread cost per leg.
- We additionally subtract a fixed **per-contract commission of $0.65/leg ×
  2 legs × 2 (open+close) = $2.60 per straddle round trip**, expressed as a
  fraction of (spot × 100). After-cost P&L (bid/ask fills + commission) is the
  ONLY ranked metric. A secondary "mid-to-mid minus modeled half-spread" variant
  is reported for context but never replaces the bid/ask-crossing primary.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable earnings events under the fixed rules.
- [ ] **After-cost short-straddle return** positive with **|t| ≥ 2.0** on the
      PRIMARY metric (bid/ask-crossed, commission-charged).
- [ ] **OOS sign stability** — IS (2022–23) and OOS (2024–26) after-cost means
      same sign, both halves N ≥ 10.
- [ ] **Placebo / pooled baseline** — earnings premium exceeds the non-earnings
      one-day short-straddle return (Welch t ≥ 2); the placebo's own mean is the
      ordinary carry to subtract.
- [ ] **Tail report (MANDATORY, not gating but decision-binding)** — full loss
      distribution: worst event, max single-event loss, fraction of total gross
      destroyed by the 5 worst events, and whether mean survives excluding the
      tail. A positive mean that is entirely a few-events-from-ruin bet is
      reported as such even if t passes.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from
      mean auto-triggers a placebo run + top/bottom-5 contributor inspection.
- [ ] **Data provenance** — spot anchoring, costs, earnings-date source
      documented (§3, §6).

No alternative metric/window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost mean ≤ 0.
- N < 30 usable events.
- OOS sign flip (crush decayed / regime-dependent).
- Placebo absorbs it: earnings premium does not exceed the non-earnings
  short-straddle carry at Welch |t| ≥ 2 (the "edge" is just being short vol).
- The mean is a tail bet: removing the 5 worst losses flips a negative full-sample
  mean to positive (i.e. the result lives or dies on a handful of gaps), AND the
  full-sample after-cost mean is ≤ 0 — report as "premium exists only until the
  tail lands."

## 9. Limitations

- ONE overnight hold per event; we do not test holding into the post-earnings
  vol path or delta-hedged variants — this is the pure short-straddle gap bet.
- Parity spot is a front-expiration approximation (ignores small rT and
  dividends); it is used only to *pick the ATM strike*, and the P&L itself is
  computed from the actual option bid/ask, so a few-cents spot error does not
  bias the P&L.
- The lake is EOD only — no intraday entry timing, no test of an open-vs-close
  entry. Coverage is 2022–2026 (no pre-2022 OOS extension available).
- A kill does NOT prove IV never overstates the earnings move; it proves that
  for these 24 names, EOD-to-EOD, after honest spread-crossing and with the fat
  left tail in-sample, the short-straddle does not clear the gate.
