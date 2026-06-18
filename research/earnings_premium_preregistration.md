# Pre-Registration: Earnings-Announcement Premium (T43)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, friction, and kill
> criteria are fixed here so a favorable specification cannot be selected after
> the fact. Standard campaign template; universal gate in
> `brain/30_campaign_findings.md`.
>
> **Relation to T07 (PEAD, already killed):** T07 tested *post*-earnings drift —
> a cohort defined by the day-0 reaction sign, holding [+1,+21] AFTER the
> announcement. T43 is the **announcement-window premium**: the return earned for
> **holding the stock THROUGH its scheduled earnings announcement** (the
> realized jump itself), measured in a tight window straddling the event. It is a
> compensation-for-jump-risk hypothesis, not a drift/momentum hypothesis. The two
> windows do not overlap.

## 1. Hypothesis (one sentence, directional, falsifiable)

Holding a stock through its **scheduled** earnings announcement earns a positive
average **market-adjusted abnormal return** over the announcement window
([-1,+1] in event-trading-day time around the first market session that prices
the release), pooled across many earnings events and in excess of the same
stock's non-earnings-day baseline.

## 2. Mechanism — why would this be inefficient?

The "earnings announcement premium" (Beaver 1968; Chari-Jagannathan-Ofer 1988;
Frazzini & Lamont 2007; Barber, De George, Lehavy, Trueman 2013): earnings dates
are known in advance and carry large, undiversifiable **jump risk** (a wide
two-sided outcome distribution). Risk-averse, attention-constrained holders
demand compensation to bear that scheduled jump; some investors *avoid* names
right before earnings, depressing the pre-event price and leaving a premium for
those willing to hold through. The effect is documented to be **strongest in
neglected / low-attention names** and to have **weakened materially** over time
as it became known and as more capital chased it.

**Honest prior:** Marginal-to-null on a *liquid mega/large-cap* universe. The
published premium lives mostly in neglected small caps; on the most-watched
mega-caps it should be heavily arbed/decayed. The honest base case is that any
positive announcement-window mean is (a) small, (b) statistically fragile after
costs, and (c) **compensated variance, not alpha** — i.e. it scales with the
event-window volatility (jump risk) rather than representing a free lunch. A
clean "it's risk premium proportional to vol, not capturable alpha" finding, or
an outright in-noise kill, is the expected and acceptable outcome.

## 3. Data + provenance

- **Universe (fixed, no post-hoc selection):** the repo catalog's single-name
  mega-caps — NVDA, AAPL, MSFT, AMZN, META, GOOGL, TSLA, AVGO, BRK-B, JPM (the
  catalog's 12 minus the two ETFs QQQ/SPY, which have no earnings) — **plus** a
  fixed list of large/mid caps with reliable yfinance earnings dates:
  AMD, ORCL, CRM, COST, NFLX, ADBE, INTC, QCOM, JNJ, PFE, MRK, LLY, ABBV, UNH,
  HD, LOW, WMT, DIS, NKE, MCD, KO, PEP, XOM, CVX, BA, V, MA, BAC, WFC, GS, MS,
  CAT, GE, HON, IBM, CSCO, TXN, T, VZ. The full list is **hardcoded in the
  runner before any results are seen**.
- **Source:** earnings dates from `yfinance` `Ticker.get_earnings_dates(limit=100)`;
  prices from `yfinance` daily `auto_adjust=True` (split/dividend-adjusted close)
  via the repo's `trader.catalysts.prices.fetch_daily`. Market benchmark = SPY,
  same source.
- **Construction & staleness:** earnings timestamps carry a time-of-day (ET).
  We use only the **calendar date**, plus the BMO/AMC convention from the hour:
  an announcement timestamped **after ~13:00 ET is AMC** (the market prices it
  the **next** session), **at/before ~13:00 ET is BMO** (priced the **same**
  session). The first session that prices the release is the event-time **day 0**
  (`t0`). All returns are adjusted-close simple returns. No derived/parity series.
- **Event/date list provenance:** `get_earnings_dates` returns up to 100 dated
  rows per ticker going back to ~2001-2002 for the older names; we keep only dates
  in the sample span. **Ex-ante knowability:** the *scheduled* earnings date is
  published in advance (companies pre-announce the call date weeks ahead), so
  knowing the announcement date is **not** look-ahead — it is the premise of the
  strategy. We do NOT use the reported EPS, surprise, or any post-event field for
  cohort membership. (Coverage caveat: a small number of yfinance dates can be off
  by a session vs the true release; the [-1,+1] window absorbs a 1-day slip.)
- **Sample span:** 2015-01-01 .. 2025-12-31. **IS = 2015-2020 (event year ≤ 2020),
  OOS = 2021-2025 (event year ≥ 2021).** Split fixed here, on event year only.

## 4. Cohort & control definition

- **Cohort (treated event):** each (ticker, scheduled earnings date) with a
  complete [-1,+1] price window around its `t0`.
- **Abnormal return:** market-adjusted, beta = 1 — for each event-day,
  `r_stock − r_SPY`; the announcement-window abnormal return is the **sum of
  daily market-adjusted returns over event days {-1, 0, +1}** (a 3-trading-day
  cumulative abnormal return, CAR[-1,+1]).
- **Baseline / control (the discipline that absorbs drift):** the SAME stock's
  **non-earnings days**. For each ticker we form a pooled distribution of 3-day
  market-adjusted CARs computed on randomly sampled non-earnings windows (windows
  that do not overlap any [-3,+3] earnings exclusion zone). The premium claim is
  **announcement-window mean abnormal return − non-earnings-window mean abnormal
  return** (both already market-adjusted), so any residual single-name drift the
  market adjustment misses is also differenced out. This doubles as the **placebo**
  (§7): the non-earnings windows must average ~0 abnormal return.
- **`t0` convention:** the first trading session on/after the announcement date
  that prices the release (BMO → same session's date; AMC → next session). Stated
  explicitly so the window arithmetic is auditable.

## 5. Measurement window + LOOK-AHEAD statement

- **PRIMARY window (event-trading-day time, inclusive):** **CAR[-1,+1]** around
  `t0`. Secondary reported (not gating): CAR[0,0] (announcement day only) and
  CAR[0,+1] (the strict no-leakage variant that buys at `t0` open-equivalent).
- **Look-ahead audit:** the only event-defining information is the **scheduled
  announcement date**, which is published ex-ante — using it is the strategy, not
  leakage. Cohort membership uses **no** post-event field (no reported EPS, no
  surprise, no realized return). The window straddles the event by construction
  (that is the *point* — we are measuring the premium for HOLDING through the
  jump, which requires a position established before the print); the day-1 leg is
  the pre-announcement entry, fully ex-ante. The strict CAR[0,+1] secondary is
  reported to show the result with zero pre-event leg for readers who want a
  position entered only at/after the print.

## 6. Friction model

- **Round-trip cost:** single-name large-cap ~**10 bps** per round trip (5 bps
  each way: spread + impact); we use 10 bps as the pre-registered, conservative
  single-name cost (cite brain/30 friction-realism: "single-name ~5-10 bps").
- **Application:** one round trip per event (enter before, exit after the window).
  After-cost premium = gross announcement-window CAR − 0.0010, subtracted once per
  event. After-cost mean and its t are the ONLY ranked metrics.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable events (expected to be far exceeded; report exact N).
- [ ] **After-cost announcement-window mean abnormal return > 0 with |t| ≥ 2.0**
      on the PRIMARY window (CAR[-1,+1]), where the mean is the cohort minus the
      same-stock non-earnings baseline (so it is a true premium, not drift).
- [ ] **OOS sign stability** — announcement-window mean has the **same sign** in
      IS (2015-2020) and OOS (2021-2025) halves, both N ≥ 10; the published
      decay-over-time claim is tested honestly here (a sign flip / OOS collapse is
      consistent with the known weakening and is reported as such).
- [ ] **Pooled baseline / placebo** — the same-stock **non-earnings** 3-day CARs
      average ~0 (|t| < 2); the premium must survive subtracting this baseline.
- [ ] **Jump-risk-vs-alpha check (decisive interpretation)** — regress / compare
      the event-window mean abnormal return against the event-window **realized
      volatility** (mean |abnormal return| or event-window return variance). If the
      premium is fully explained by high event-window vol (premium ≈ k · vol,
      Sharpe of the announcement-window CAR is unremarkable), classify as
      **compensated jump-risk variance, not alpha**, even if the mean is positive.
- [ ] **Too-good tripwire** — announcement-window Sharpe > 3, win rate > 85%, or
      median far from mean auto-triggers a placebo re-run + top-5 contributor
      inspection before any write-up.
- [ ] **Data provenance** — yfinance earnings dates + adjusted prices, BMO/AMC
      convention, documented in §3.

No alternative window may replace CAR[-1,+1] as PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea (as a *capturable* edge) if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost mean ≤ 0.
- N < 30 usable events under the fixed rules.
- OOS sign flip (premium decayed / regime-dependent — the expected outcome per
  the decay literature).
- Non-earnings placebo is NOT ~0 (|t| ≥ 2): the "premium" is contaminated drift,
  not an announcement effect.
- The premium is fully explained by event-window volatility (compensated
  jump-risk variance, not alpha) → kill as *alpha* even if the mean is positive,
  and label it a risk premium.
- Fewer than 5 events / 1-2 tickers drive the result (remove top contributors →
  effect vanishes).

## 9. Limitations

- **Universe is liquid large/mega-cap** — exactly where the published premium is
  weakest. A kill here does NOT prove the earnings-announcement premium is dead in
  the neglected small-cap names where it historically lived; we cannot test those
  cleanly on free data with reliable earnings dates, so the claim is scoped to
  this universe.
- **yfinance earnings dates** can occasionally be off by a session or include a
  re-stated/duplicate date; the [-1,+1] window absorbs a 1-day slip and we drop
  duplicate dates, but a few mis-timed events are possible (reported as a caveat,
  not hidden).
- **BMO/AMC inference from the timestamp hour** is a heuristic; if yfinance lacks
  a time-of-day for an event we default to **AMC** (the conservative assumption
  that the market reacts next session). Documented in the runner.
- Market-adjusted (beta = 1) abnormal returns slightly mis-state risk for
  high-beta names; the same-stock non-earnings baseline absorbs most of the
  residual. Full Fama-French / estimated-beta adjustment is out of scope.
- This tests the *average* premium; it does not test conditional variants
  (pre-earnings run-up, IV-rich names, neglect proxies), which would each need
  their own pre-reg.
