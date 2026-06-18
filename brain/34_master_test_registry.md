# Brain 34 — Master Test Registry: the 50-strategy falsification campaign

Date: 2026-06-14
Status: ACTIVE roadmap. This is both the execution plan and the table of
contents for the eventual research paper / open-source writeup.

## Purpose & principles

Goal: ~50 **genuinely distinct** strategy families, each tested fully end-to-end
under one rigorous gate, to produce a comprehensive, honest, publishable
negative result ("retail edge-mining on accessible data does not survive
rigorous testing") plus the artifact taxonomy that explains *why*.

**Breadth × rigor, NOT count.** Value comes from diversity across asset classes
and mechanisms, not from a big number. Variations of one idea do NOT count as
separate tests. Expect ~48 of 51 to be kills; a few marginal (e.g. CEF). The
deliverable is the *map*, not a survivor.

**Universal gate (every test, no exceptions — from brain/30):**
pre-registration → friction realism → look-ahead audit → OOS sign stability →
pooled baseline → matched-control permutation → too-good tripwire → data
provenance. A test that skips a gate is not "done."

Status legend: ✅ done · 🔄 in-flight · ⬜ planned. Data: 💾 owned · 🆓 free ·
💲 paid (monthly).

---

## A. Index options / volatility — QQQ (owned 💾)
- ✅ **T01** Intraday iron-condor sweep (**SPY**, 5-day early-lab plumbing smoke — NOT a gated/OOS run like T19+) — *no edge* (every *trade-producing* config of 72 lost; least-bad 3 trades, 0% win, −$154). Validated the harness, not a strategy verdict.
- ✅ **T02** Iron-condor cross-regime — *no edge* (wins small, loses big).
- ✅ **T03** QQQ option features (GEX, vol-of-vol, 25Δ skew, term) — *no edge*.
- ✅ **T09** QQQ options microstructure (spread/depth/large quotes) — *no edge*.
- ✅ **T19** VRP daily iron condor (signed pre-reg) — *KILL, mechanism null*.

## B. 0DTE / intraday options — QQQ (owned 💾, collecting now)
- 🔄 **T20** 0DTE short-premium (defined-risk, mechanical) — *data backfilling*.
- ⬜ **T27** 0DTE dealer-gamma-conditioned intraday reversion. *Mech: retail
  0DTE flow lopsided; gamma sign predicts intraday mean-revert vs trend.*
- ⬜ **T28** Opening vol-crush / intraday vol-of-vol. *Mech: systematic AM IV
  decay.*

## C. Single-name equity options (💾 ALREADY ON CURRENT ~$40 ThetaData plan — verified 2026-06-14: ~15,553 option roots accessible, 2020+; EOD collection in flight)
- ✅ **T22** Index dispersion / correlation risk premium (QQQ vs 26 constituents) — *real premium (implied ρ 0.38 > realized ρ 0.35; GROSS vega-neutral book t=+1.98, win 58%) but the 26 single-name straddle round-trips at realized quoted half-spreads cost 365% of the gross edge → after-cost −14%/mo (t=−5.03, win 21%), OOS-stable (IS t=−3.36, OOS t=−3.73), incremental-α over short-index-vol t=−5.47, sign-flip placebo p=1.0. KILL; friction-scale noise (class #2) — NOT crash compensation (corr(ret,index move)=+0.03). N=53. 26-name equal-weight proxy for QQQ (no MSFT, equal not cap weights). Confirms the pre-registered "expensive to harvest."*
- ✅ **T23** Single-name earnings IV crush — *KILL: pre-earnings IV overstates the move (+1.59% crush gap) but the short straddle loses −0.59%/event (t=−3.61) after honest single-name bid/ask + tail; corr(P&L, move)=−0.84 = compensated jump variance, not alpha; doesn't beat non-earnings carry (Welch t=−0.87). N=414, 24 names. Class-2 friction + jump tail. (Used own put-call-parity spot anchor — immune to the foundation split-spot bug.)*
- ✅ **T24** Single-name vol term-structure carry — *KILL: cross-sectional vega-neutral calendar ranked on the ≈30/≈90d ATM slope (26 names, N=53) loses after cost (−2.73/period, t=−3.41) and adds ZERO alpha over an unconditional short-vol book (residual t=−0.18); placebo p=1.000 — random ranks BEAT the slope; even at zero friction the LS book is negative. Class-2 in-noise + short-vol-beta confound. Caveat: EOD straddle proxy re-strikes ATM at exit (omits gamma/path), so the short-vol book's tail is understated — but that only makes short-vol worse, never rescues the slope signal.*
- ✅ **T25** Single-name 25Δ skew dynamics — *KILL: skew real & large (median +3.37 vol-pts, +90.7% of days) but signal-null — tertile long–short net −0.05%/wk t=−0.10, IS +0.12% → OOS SIGN-FLIP −0.24%, placebo p=0.89. Premium framing = short-vol+short-delta beta in disguise: residual alpha t=−33.50 (β_vol+0.13, β_mkt+0.38). N=219 weekly / 5,197 rows / 24 names. Re-run on parity-fixed foundation + 25Δ delta-tolerance band (drops ~27 off-band thin-wing dates; verdict unchanged); prior "−319%/−205-vol tail" was a split-spot artifact (removed). Friction-scale noise + disguised-beta, same lesson as VRP T19.*
- ⛔ **T26** Hard-to-borrow / put-call-parity — *DATA_WALL: easy-to-borrow mega-caps → implied carry q*≈0 (pooled median −1.9 bps/yr). MECHANISM (corrected): q* = borrow + dividend; borrow≈0 → q* IS dividend yield, corr(div,q*)=+0.949 (payer +27 vs zero-div −44 bps) — a factor tilt, not short-supply. Low-minus-high spread +0.57% after-cost t=+0.64 (N=53), ≈ placebo, OOS flip. Re-run on parity-fixed foundation (prior yfinance-mismatch/HON-pathological framing was stale). Wrong universe for the OR-W HTB effect — cleanly documented.*

## D. Crypto — 24/7, retail-heavy (🆓 exchange APIs)
- ✅ **T29** Perp funding carry, cross-sectional alt tail — *KILL: after-cost −2.6%/yr (t=−0.05), IS +18bps/day → OOS −19bps/day flip. Funding +31.6%/yr gross is real but ~81% paid back by the short-perp price leg (−25.7%/yr) + ~6bps taker fees → risk premium, not alpha. Survivorship SOLVED via data.binance.vision (retains delisted; 18/80=23% dead); survivor-only ≈ cohort → not a mirage. Placebo ~0. RE-VERIFIED on epoch-fixed data (matched 80-sym): numbers & kill direction unchanged; the ms→µs fix did not rescue it.*
- ⛔ **T30** Spot-perp basis — *MERGED into T29 (no-padding): perp basis ≈ funding,
  the same cash-and-carry trade; not double-counted.*
- ✅ **T31** Cross-exchange perp funding dispersion (Binance vs OKX) — *KILL (friction-scale noise): real & sign-stable gross dispersion 0.58 bps/8h (t=51, all 19 symbols) but ≪ 20 bps two-venue round trip → after-cost −0.38 bps/interval (t=−33), win 2%. Bybit geoblocked (403), OKX public history ~3mo wall; cost wall is window-independent.*
- 🟡 **T32** Crypto VRP (Deribit DVOL) — *SPLIT/MARGINAL, the campaign's most-alive result. BTC: mechanism is REAL (corr +0.18, monotone quartiles — unlike the mechanism-null equity VRP at 0.01), survives the FTX/LUNA tail (worst days priced rich ex-ante), full-sample t=5.10 net of 2× cost. BUT decaying: IS t=5.02 → OOS t=1.88 (<2 alone) → last-18mo t≈1.0 (flat); and it's a variance-swap-replication PROXY, not a tradeable margined options book. ETH KILLED (OOS sign-flip). NOT deployed — watchlist, alongside CEF activist (T13).*
- ✅ **T33** Crypto time-series momentum / trend-following — *KILL: levered/timed BETA, not alpha. N=90 long-flat net +79.8%/yr but Sharpe 0.79 < buy-and-hold BTC 0.99 (−93% vs −77% DD); random-timing placebo w/ matched exposure earns +72.8%/yr (~91% of return). Primary after-cost t=1.79<2. OOS sign-stable = just persistent bull beta.*
- ✅ **T34** Stablecoin depeg mean-reversion — *KILL (survivorship/tail trap): survivor-only +3.1% (t=3.74, 100% win) flips to −16.0% once UST's −67.6% death is in the sample; drop-worst flips sign; N=4. Textbook pennies-before-a-steamroller. BONUS: agent found+fixed a real ms→µs epoch bug in crypto_data.py corrupting all 2025-26 bars (T29's 2025 tail affected — kill direction unchanged, re-verify numbers in paper pass).*

## E. Futures — term structure & carry (💲 ~$30–60/mo Norgate/Databento)
- ⬜ **T35** Commodity roll yield / carry. *Mech: long-only ETF holders pay roll.*
- ⬜ **T36** Commodity seasonality (ag / energy). *Mech: weather/harvest calendar.*
- ⬜ **T37** Futures term-structure / backwardation signal.
- ⬜ **T38** COT positioning signal. *Mech: commercial vs spec imbalance.*
  (Continuous-contract construction = a data-quality trap; control the roll.)

## F. Equity events & structural flow (🆓 EDGAR + yfinance)
- ✅ **T07** PEAD — *LOOK-AHEAD KILL*.
- ✅ **T08** 8-K item-type study — *no edge*.
- ✅ **T12** IPO lock-up expiry — *KILL (decayed)*.
- ✅ **T14** SPAC trust arb — *KILL (below T-bills)*.
- ✅ **T39** Index reconstitution / "index effect" (S&P add/delete, announce→effective) — *KILL: decayed null (add CAR +0.48% gross/+0.38% net, t=1.11, median<0) AND placebo-absorbed (same-name random windows +0.41%, t=2.85 → name drift not flow). Deletions untestable (~80% yfinance survivorship); free announcement-date series doesn't exist, used ex-ante effective−5td proxy.*
- ⛔ **T40** Cash-merger arb spread — *DATA_WALL: completed-deal targets delist on close and yfinance PURGES them — 2/24 completed priceable (~100% true purge), vs broken survivors (NXPI −11.8%/yr) that yfinance RETAINS = INVERSE survivorship. The arb spread lives in exactly the population the free source deletes. Placebo null, EDGAR announce-anchoring worked. Needs Tiingo/CRSP (delisted-retaining). Verified live (10/10 completed targets return 0 rows).*
- ✅ **T41** Buyback-announcement drift (8-K Item 8.01) — *KILL (friction-scale #2): broad cohort PASSES the full gate (after-cost +1.08%, t=+3.39, N=1303) but is a small-cap illiquidity mirage — 64% sub-$10M/day. Load-bearing kill = the clean tradeable slice (≥$10M/day MEASURED ADV, N=208): +0.21% (t=+0.32) with IS +3.29% → OOS −0.64% sign-flip. (The −0.97% tiered-cost figure is contaminated by 56% missing-ADV charged max cost — NOT load-bearing; the tradeable-slice flip is.) Class-2.*
- ✅ **T42** Spin-off post-event drift (Form 10-12B, forced index-fund selling) — *KILL: decayed null. Spinco 1-mo CAR −0.07% gross/−0.27% net, t=−0.03, N=104 (survivorship-safe, incl. AFIIQ/BXRXQ bankruptcies); IS −0.22%/OOS +0.05% sign-unstable, pooled placebo clean −0.01% → genuine null. Greenblatt forced-selling premium arbitraged away (spin-off ETFs + index fast-tracking). Well-powered, no data wall.*
- ✅ **T43** Earnings-announcement premium — *real but KILL: gross +0.34%/after-cost +0.24% (t=1.85, <2); IS +0.46% (t=2.76) → OOS −0.01% (t=−0.07) decay; corr(premium, window-vol)=+0.73 → compensated jump-risk, not alpha; N=2156, placebo null. Scoped liquid mega/large-cap.*
- ✅ **T44** Insider cluster buying (Form 4, ≥2 insiders/30d) — *KILL: forward market-adj CAR is NEGATIVE — gross −1.46%/after-cost −1.86% (t=−0.83) at 3m; IS +0.34% → OOS −3.82% sign-FLIP; same-name placebo also −4.87% (these neglected names sit in a down-drifting pocket — "beats placebo" vacuous); drop-top-5 → −5.55%. N=121 (84/207 clusters lost to yfinance microcap survivorship → biases survivors UP, so kill is conservative). Decayed/never-replicated.*
- ✅ **T45** 13F institutional cloning (filing-date) — *KILL: cloning 12 famous managers' NEW positions from the FILING date earns after-cost −0.56% at 3m (t=−2.09, wrong sign), LOSES to same-name placebo (+0.33%), OOS sign-flips (IS +1.32%/t=3.97 → OOS −2.54%/t=−6.07). Mean filing lag 47.0 days = the structural killer — info is ~1.5mo stale by disclosure. N=6,002 (68.6% Burry's high-churn book). Decayed; trade-date version untested.*
- ⬜ **T46** High-short-interest / squeeze signal. *Mech: forced covering.*

## G. Catalyst / news (owned 💾)
- ✅ **T17** News catalog Phase 2 (27 cohorts) — *4 baseline artifacts*.
- ✅ **T18** product_news matched-control — *KILL (composition)*.
- ⬜ **T51** LLM news-interpretation predictive test. *Mech: reasoning-model
  interpretation on names the fast money ignores; the only "news" angle not
  already dead. Low prior; hindsight-leak risk severe.*

## H. CEF / special situations (🆓 + Tiingo cheap)
- ✅ **T13** CEF activist follow (Saba 13D) — *MARGINAL FAIL*.
- ✅ **T15** CEF broad discount tilt — *bounded, uncapturable*.
- ✅ **T16** CEF survival backtest — *KILL (data glitch)*.
- 🔄 **T21** CEF resolution-selection (matched control + NAV) — *Phase 5,
  pending paid Tiingo decision*.

## I. Cross-sectional / multi-asset / macro (🆓)
- ✅ **T04** Cross-sectional pairs / RV — *KILL (SPY/IVV microstructure)*.
- ✅ **T05** Multi-asset regime signals — *no edge*.
- ✅ **T06** Intraday QQQ strategies — *DATA KILL (parity-derived)*.
- ✅ **T10** Small / illiquid universes — *no edge*.
- ✅ **T11** Pre-2010 SPY OOS — *no edge*.

## J. Seasonality / calendar (🆓)
- ✅ **T47** FOMC pre-announcement drift (Lucca–Moench) — *KILL (decayed: IS
  t=2.08 → OOS t=−0.02; pooled t=1.35 sits inside the placebo |t| band).*
- ✅ **T48** Turn-of-month effect — *KILL: +3.4 bps/day gross (t=1.05, below placebo 1.93); IS +5.8 bps (t=1.21) → OOS +0.8 bps (t=0.18) — decayed seasonal, in-noise.*
- ✅ **T49** Sell-in-May / Halloween indicator — *KILL: winter−summer +0.48%/mo but t=1.12 (noise); seasonal Sharpe 0.68 < buy-and-hold 0.77 — lower drawdown is exposure reduction (50% in cash), NOT alpha. Exposure-driven, no survivable edge.*
- ✅ **T50** Day-of-week / pre-holiday effects — *KILL both: Monday effect gone & sign-reversed (+0.054%/day, t=0.22); pre-holiday +5.3bps gross but t=0.93 < placebo 1.94, cost-eaten. Decayed + friction-scale noise.*

---

## Tally & data-cost rollup

- **Tested: 40 · In-flight: 2 (T20, T21) · Planned: 8 · Merged: 1 → 51 total.**
  Authoritative count: `research/CAMPAIGN_SCOREBOARD.md` (regenerated from this
  file by `scripts/build_campaign_scoreboard.py`). **40 tested = 27 kill + 8
  no-edge + 3 marginal (T13 CEF activist, T15 CEF discount, T32 BTC VRP) + 2
  data-wall (T26, T40).** Single-name vol-surface cluster COMPLETE: T22 dispersion
  (KILL, friction-scale — the correlation premium is real but single-name spreads
  = 365% of the gross edge), T23–T26 done. Crypto cluster DONE (5 tested). Next:
  0DTE cluster (T20, T27, T28) when that data lands; finish CEF (T21).
- **Free / owned / current-plan: ~31 of the planned** — including single-name
  options T22–T26 (CORRECTED 2026-06-14: these are on the current ~$40 ThetaData
  plan, NOT a paid upgrade; ~15,553 roots accessible, EOD basket collecting now).
  Collect-then-cancel: pull what the tests need while subscribed, own it forever.
- **Only genuinely extra cost: futures T35–T38** (~$30–60/mo, DIFFERENT vendor —
  Databento/Norgate; ThetaData doesn't do commodity futures). Optional, one
  month, deliberate go-decision. Everything else needs no spend beyond current.

## Execution waves

- **Wave 1 (free, now): seasonality/calendar (T47–T50) + equity events
  (T39–T46)** — daily data, EDGAR, fast, distinct, several are famous published
  anomalies (good "does it survive our gate?" content).
- **Wave 2 (free): crypto (T29–T34)** — survivorship-safe universe construction
  FIRST; then funding/basis/vol.
- **Wave 3 (owned): 0DTE (T20, T27, T28)** — once the backfill completes.
- **Wave 4 (paid, go-decision): single-name options (T22–T26) + futures
  (T35–T38)** + finish CEF (T21).
- Each test: pre-registration doc → run → decision doc → registry status update.

## Standard per-test artifact

Every test produces: (1) a pre-registration entry (hypothesis, data, gate,
kill criteria) BEFORE results, (2) a runnable script, (3) a decision doc with
the verdict and which artifact class (if killed). Consistent format so the 52
compose into the paper mechanically.
