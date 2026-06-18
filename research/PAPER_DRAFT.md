# Does Any Accessible Edge Survive Rigorous Testing? A Pre-Registered Falsification Campaign Across ~50 Strategy Families

*Complete draft. The results table (§7) is generated from
`research/CAMPAIGN_SCOREBOARD.md` and the concluding verdict (§8) from the closed
campaign. All 40 tested families have a committed verdict — the single-name
vol-surface cluster is now complete with T22 (index dispersion) landed as a
friction-scale kill. All numbers are traceable to committed decision records
under `research/*_decision.md`, `brain/decisions/`, and the registry
`brain/34_master_test_registry.md`.*

---

## 1. Abstract

A single researcher, working on a hobbyist budget with free and retail-accessible
data, pre-registered **51** *genuinely distinct* strategy families spanning index
and single-name options, crypto derivatives, equity events and structural flow,
catalyst-driven news, closed-end-fund special situations, cross-sectional/macro
signals, and calendar seasonality; **39 reached a verdict** (the rest are
in-flight, planned, or merged). Each family passed — or, far more often, failed — a
single fixed eight-step gate: pre-registration, friction realism, a look-ahead
audit, out-of-sample sign stability, a pooled-baseline subtraction, a
matched-control permutation test, a "too-good-to-be-true" tripwire, and a
data-provenance check. **Thirty-six of the thirty-nine reached an outright
negative verdict** (kill, no-edge, or data-wall); only three resisted a clean
kill, and none was deployable. Critically, *every* statistically promising result,
without exception, decomposed under scrutiny into one of a small number of
recurring explanations: look-ahead leakage, friction-scale noise, data glitches,
derived/fake data, pooled-baseline (composition) contamination, classifier
hindsight, survivorship/tail traps, or the broadest category of all — compensated
risk and beta in disguise. The two largest buckets — decay-into-noise and
compensated-risk/beta — are precisely the classes a conventional deflated-Sharpe
screen passes. The three effects that did *not* cleanly die (the closed-end-fund
discount/activist effect and the BTC crypto volatility-risk premium) were real in
mechanism yet not deployable: capacity-limited and uncapturable in the first case,
decaying and proxy-not-tradeable in the second.

The contribution of this work is therefore **not an edge**. It is (a) a reusable
falsification methodology that catches at least seven distinct classes of false
positive — several of which a conventional deflated-Sharpe screen would pass —
codified as a shared gate (`src/trader/research/gate.py`); (b) an artifact
taxonomy, illustrated throughout with the campaign's own real numbers, that
explains *why* each apparent edge was a mirage; and (c) the data infrastructure
assembled to run the tests honestly. The headline negative result — that retail
edge-mining on accessible, mostly daily-frequency data on liquid instruments does
not survive rigorous testing — is, we argue, sharper and more useful than any of
the fragile positives it replaces.

---

## 2. Motivation

The retail quantitative-trading landscape is saturated with backtests that look
extraordinary and deploy catastrophically. The gap between the two is almost never
a bug in the trading logic; it is a defect in the *evaluation*. A backtest is a
measurement instrument, and the dominant failure mode of that instrument is to
measure something other than a tradeable edge — survivorship, look-ahead, beta,
friction-free fills, a single corrupt row — while reporting it as alpha.

The honest question is not "what is my best strategy?" but "does *any* accessible
edge survive a test designed to kill it?" That framing matters because it inverts
the usual incentive. A researcher optimizing a strategy is motivated to find
configurations that pass; a researcher running a falsification campaign is
motivated to find the reason each apparent pass is fake. The first process
overfits by construction. The second, if its gate is strict enough, converges on
the truth even when the truth is disappointing.

We adopt the efficient-markets prior honestly and explicitly. The most-arbitraged
corner of finance — liquid, public, daily-frequency, US large-cap instruments — is
exactly where a hobbyist with free data is *least* likely to find a durable edge,
because thousands of better-capitalized participants have already competed it
away. The interesting prior is not "markets are perfectly efficient" (they are
not) but "any inefficiency accessible on free data and liquid instruments is
either already arbitraged, too small to clear costs, or compensation for a real
risk you are being paid to bear." A campaign that tests ~50 families against that
prior, and reports the kills as carefully as it would have reported a survivor,
produces something rarer than an edge: a credible map of where the edges are *not*,
and a tested explanation for each absence.

This is a deliberately adversarial exercise against one's own hopes. Several of
the families tested here are famous published anomalies — the pre-FOMC drift, the
sell-in-May/Halloween effect, the turn-of-month effect, the index-reconstitution
"index effect," post-earnings-announcement drift. Asking "does this survive *our*
gate, on free data, today?" is itself the content: a published anomaly that has
decayed into the placebo band is a finding, not a failure.

---

## 3. Methodology: the universal gate

Every test in the campaign — no exceptions — passed through the same eight-step
gate before any result could be written down anywhere. The gate is ordered, and a
test that skips a step is not "done." Each step exists to catch a specific class of
false positive that the campaign actually encountered; the artifact taxonomy in §4
is, in effect, the catalog of failures each gate step was built to stop.

The numeric core of the gate is codified as a single shared, pure **reference
module**, `src/trader/research/gate.py`, whose `evaluate_gate(...)` returns every
step's PASS/FAIL line and is itself unit-tested (`tests/financial/test_research_gate.py`).
Honesty about the implementation, because it bears on the methodology claim: the
per-test modules do **not** all call this evaluator at runtime — most re-implement
the numeric core (the one-sample t, after-cost expectancy, OOS split, placebo) in
their own `evaluate_gate`, sharing gate.py's conventions (t-stat with `ddof=1`
against null 0; after-cost mean; OOS same-sign with both halves N≥10; one-sided
permutation; the Sharpe/win-rate/MAD-gap tripwire) rather than its code. An
adversarial code review of the campaign found that this had let a few hand-rolled
gates drift *weaker* than the reference — the insider-cluster (T44) and 13F (T45)
placebo lines tested only "beats the placebo mean" rather than the stricter
"placebo-null AND beats it"; the 13F and spin-off (T42) OOS checks did not enforce
the N≥10-per-half floor in-gate; and crypto momentum (T33) used a Sharpe/win-rate
tripwire that omitted the MAD-gap and single-row-concentration checks. **These
divergences have since been brought into line** (the placebo lines now require a
null placebo, the OOS floor is enforced in every event study's gate, and T33 calls
the shared `too_good_tripwire`); no verdict changed, because each was already
killed on other lines and the alignment only *tightens* the gate. The
genuinely-shared plumbing those tests duplicated — the market-adjusted event-study
machinery and the two-sample Welch t — is now consolidated into
`trader/research/event_study.py` and `gate.welch_t`. The remaining step toward the
ideal (every test calling `gate.evaluate_gate` directly, so a dropped step is
impossible rather than merely conspicuous in review) is a tracked refactor; what the
shared modules buy *today* is one canonical definition that every per-test gate is
audited — and now demonstrably aligned — against, pinned by the test suite.

**1. Pre-registration.** The hypothesis, cohort definition, measurement windows,
the sample-size (N) arithmetic, and the explicit kill criteria are written and
committed *before* any result exists. *Why:* it removes the single largest source
of overfitting — specification search after seeing the data. If a favorable window
or threshold cannot be selected post hoc, most "edges" never appear. Every test
has a committed `*_preregistration.md`; the crypto-VRP pre-registration even bakes
in the lesson from the prior equity-VRP kill (a non-sign-only mechanism gate) so
the favorable specification was closed off in advance.

**2. Friction realism.** Commissions plus slippage are charged on every leg, and
*after-cost* expectancy is the only metric the campaign ever ranks or filters on.
*Why:* a signal that is real in basis points but smaller than its round-trip cost
is not an edge; it is noise wearing a t-statistic. Ranking on a pre-cost metric is
how the cross-sectional lab nearly reported 28 "survivors" that were 2.88 bps of
mean against ~5 bps of friction (§4.2).

**3. Look-ahead audit.** An explicit written statement of *what information defines
the cohort* and a proof that the measurement window starts strictly after it.
*Why:* the most seductive backtests leak the future into the past through window
arithmetic. PEAD (§4.1) is the canonical case: the cohort was defined by the day-0
return while the cumulative abnormal return *included* day 0. The audit forces the
window arithmetic into the open.

**4. Out-of-sample sign stability.** An early/late split; the effect must keep the
same sign in both halves, each with N ≥ 10. *Why:* a genuine effect persists; a
mined one flips. The clearest kills in the campaign are sign flips — funding carry
went from +18 bps/day in-sample to −19 bps/day out-of-sample; the FOMC drift went
from t = +2.08 to t = −0.02; the earnings premium collapsed from +0.46% (t = 2.76)
to −0.01% (t = −0.07).

**5. Pooled baseline.** Cohort return minus the universe baseline, plus an up/down
symmetry check. *Why:* a cohort inherits the drift of the universe it is drawn
from. If "after a big *up* day" and "after a big *down* day" both drift the same
sign, the drift is not caused by the event — it is the universe's beta. The
smoking-gun symmetry test caught the Phase 2 mega-cap-beta trap (§4.5): in 11 of 13
two-direction categories, the up and down cohorts drifted the *same* sign.

**6. Matched-control permutation.** Composition-matched (ticker, year) placebo
cohorts; a claim requires both a permutation p < 0.05 *and* a net |t| ≥ 2. *Why:* a
pooled baseline is insufficient when a cohort *clusters* in high-drift cells. A
cohort that is 23/48 Tesla and 24/48 in 2020 will beat the pooled average with no
catalyst effect at all. The matched control builds placebo cohorts with the
*identical* (ticker, year) composition; if the real cohort sits inside that
placebo distribution, there is nothing there (§4.6).

**7. Too-good-to-be-true tripwire.** A Sharpe above 3, a win rate above 85%, or a
median far from the mean automatically triggers a placebo run and a by-hand
inspection of the top contributors *before* the result may be recorded. *Why:* on
accessible data, "too good" is overwhelmingly an artifact, not an edge. The
tripwire is deliberately built around robust (median-absolute-deviation) statistics
and a single-row concentration check, because the very outliers it hunts — the 224%
data glitch, the stablecoin death — inflate the standard deviation and thereby hide
themselves from a naive z-score. A high win rate with a fat negative tail (the
short-vol signature) is itself the tripwire, not a pass.

**8. Data provenance.** Every new series documents its source, its construction, and
its staleness before use. *Why:* the most embarrassing false positives are not
strategy errors but data errors — a parity-derived series masquerading as spot, an
epoch-unit change corrupting every recent bar, a vendor glitch printing an
impossible 224% one-day move. Provenance discipline is the only defense that runs
*before* the test does.

A structural note on the gate: steps 2, 4, 5, 6, and 7 are numerically checkable
and are enforced by the shared evaluator. Steps 1 and 8 — pre-registration and
provenance — cannot be inspected by a pure function (no function can read a git
commit or a data-source note), so they are surfaced as explicit acknowledgement
flags that *default to False*. A forgetful caller therefore *fails* the gate rather
than silently passing it. That default is the whole point.

---

## 4. The artifact taxonomy

This is the intellectual heart of the campaign. Every kill, without exception,
belongs to one of the classes below, and each class is illustrated with the
campaign's best real example and its actual numbers. The taxonomy is not a list of
mistakes to avoid in the abstract; it is the empirical distribution of *how
apparent edges on accessible data turn out to be fake*. A future claimant who can
name which class their would-be edge most resembles, and show it does not apply, has
done most of the work of due diligence.

### 4.1 Look-ahead leakage — *PEAD (T07)*

The event that *defines* the cohort overlaps the window that *measures* its return.
In the post-earnings-announcement-drift test, the cohort was sorted by the day-0
(surprise-day) return while the cumulative abnormal return was computed *including*
day 0. The drift was, in part, the day-0 return measuring itself. When the window
was corrected to start strictly after the defining information —
CAR[+1, +21] — the effect was −3.70% and the sign *flipped*. **Defense:** the
measurement window must start strictly after everything that defines the cohort,
and the window arithmetic must be audited explicitly. The precise rule the campaign
adopted after PEAD is *"the window starts strictly after the cohort-defining
information"* — which is not always the same as *"the window excludes t0."* Where t0
is itself the surprise (PEAD's earnings day, the spin-off's first trading day), t0
is excluded: spin-off drift, for instance, measures CAR[+1, +21]. But where the
cohort is anchored to a public EDGAR filing whose content is knowable *before* t0 —
the insider-cluster (T44) and 13F (T45) studies, anchored to the filing date — the
day-0 return is legitimately ex-ante tradeable, so those two studies measure
CAR[0, +63] and deliberately include t0. Both conventions honor the real rule (no
information from after the anchor leaks into the window); they differ only in
whether the anchor itself precedes t0. We state this explicitly rather than let the
blanket phrase "excludes t0" stand, because it is literally false for the two
filing-anchored studies.

### 4.2 Friction-scale noise — *SPY/IVV "28 survivors" (T04) and cross-exchange funding (T31)*

The signal is real — sometimes overwhelmingly significant — but smaller than its
round-trip cost. The cross-sectional relative-value lab produced 28 apparent
survivors; all were SPY/IVV-type microstructure: a mean of **2.88 bps against
roughly 5 bps of friction**. They ranked as edges only because they were ranked on
a *pre-cost* metric.

The sharpest illustration of this class is the cross-exchange perp-funding
dispersion test (T31). The gross dispersion between Binance and OKX funding is real
and astonishingly stable — **0.58 bps per 8h, t = 51, the correct sign across all
19 symbols**. A naive reading would call a t of 51 a once-in-a-career discovery.
But the two-venue round trip costs roughly 20 bps, so after cost the same signal is
**−0.38 bps per interval (t = −33), with a 2% win rate**. The t-statistic measures
that the spread is genuinely *there*; it says nothing about whether it is
*harvestable*. **Defense:** report expectancy *after* friction, always; never rank,
filter, or get excited on a pre-cost metric. A huge gross t-stat is a property of
the data's regularity, not of the edge's tradeability.

### 4.3 Data glitches — *Tiingo 224% CEF (T16) and the crypto ms→µs epoch bug (T34)*

A single impossible row inflates the mean. The closed-end-fund survival backtest on
real Tiingo data printed a +10.5% mean that dissolved on inspection into outliers,
sector drift, and one **224% single-day "return"** that no instrument produced —
a vendor glitch. The median was ≈ 0. A second, separately-fixed instance of this
class: Binance switched its kline `open_time` field from milliseconds to
microseconds in 2025, and a hardcoded `unit="ms"` silently corrupted *every*
2025–2026 bar (they decoded to 1970), affecting the crypto-carry tail. **Defense:**
a median-versus-mean sanity check on every positive result; winsorize and re-test;
and inspect the top-5 contributors of *every* positive result by hand. The
campaign's tripwire encodes exactly this — its robust MAD-gap and single-row
concentration checks fire precisely when a near-constant core hides one monster row.

### 4.4 Derived/fake data — *intraday "Sharpe 11" (T06)*

The series is not what it claims to be. The intraday QQQ strategies lab produced a
Sharpe of **11** — a number so far beyond plausibility it could only be an
instrument error. It was: the "minute spot" series was *put-call-parity-derived*,
not real traded spot, so the strategy was, in effect, trading against its own
construction assumption. The lab was disabled. **Defense:** a provenance check on
every new series — who built it, from what inputs, with what staleness — *before* it
is allowed into a test. A Sharpe of 11 is never an edge; it is a receipt for a data
error.

### 4.5 Pooled-baseline contamination — *Phase 2 mega-cap-beta trap (T17)*

The cohort inherits the universe's drift. The 1,512-event catalyst catalog yielded,
under a pre-registered N ≥ 30 / |t| ≥ 2 / OOS-stable gate, **5 surviving cohorts
out of 27**. The pooled baseline across all 1,492 events with computable drift was
**+2.39%** — the systematic outperformance of mega-cap tech versus SPY across
2020–2026 (NVDA ~10×, AVGO ~5×, MSFT ~2×). Four of the five "survivors" sat within
~1% of that baseline: they were the regime, not the catalyst. The smoking gun was
the up/down symmetry test — in **11 of 13** two-direction categories, the up and
down cohorts drifted the *same* sign, which is impossible for a genuine
event-driven effect. **Defense:** subtract the universe baseline from every cohort
return, and run the up/down symmetry check as a standing diagnostic. The
five-survivor headline would have been a mirage without it.

### 4.6 Composition effects + classifier hindsight — *product_news matched-control (T18)*

This is the subtler successor to §4.5, and it required *two* new gate ideas to kill
the campaign's most stubborn candidate. After the pooled-baseline correction, one
cohort survived: `product_news__up`, raw CAR[+1, +21] of **+9.26%**. But the cohort
*clustered*: **23 of 48 events were Tesla, 9 were NVDA, and 24 of 48 fell in 2020
alone** (Tesla's +700% year). A pooled baseline cannot see this; a *matched* one
can. The matched (ticker, year) baseline — the mean drift over all eligible quiet
days for the *same* ticker in the *same* calendar year — was **+9.12%**, leaving a
net of **+0.14% (t = +0.07)**. A composition-matched permutation test (2,000 placebo
cohorts with identical (ticker, year) composition) put the observed mean at the
**47th percentile** of its own placebo distribution: permutation p = 0.473. A
random same-composition cohort does this half the time. There was nothing there.

The same test exposed a seventh, related class. The catalog's cohorts were built by
an LLM classifier labeling *historical* events — and a model labeling the past knows
what happened next. High-confidence events showed +12.69% raw versus +7.70% for
med/low confidence, which looks like the classifier's confidence "predicting"
returns. But net of the matched control the gap was +1.14% versus −0.31%: the
confidence gradient was *also* composition (the classifier is more confident about
famous Tesla/NVDA product events, which live in high-drift cells). **Defense:** treat
LLM-built cohorts as contaminated by construction — window discipline cannot remove
hindsight that enters at *selection* time; only a composition-matched control
absorbs it. And check whether classifier confidence "predicts" returns net of that
control (it should not).

### 4.7 The recurring pattern — compensated risk and beta in disguise

This is the broadest and most important class, because it is where the *honest*
strategies — the ones with a real economic mechanism — go to die. Here the effect
is genuinely present, statistically real, and *not* an artifact in the §4.1–§4.6
sense. It is simply not *alpha*. You are being paid to bear a risk, or you are
holding levered/timed beta, and a properly risk-adjusted or exposure-matched
comparison reveals there is no edge per unit of risk taken.

- **Sell-in-May / Halloween (T49).** Winter (Nov–Apr) months average +1.19% versus
  summer (May–Oct) +0.71% — directionally the famous pattern, but the gap is
  in-noise (Welch t = +1.12). Decisively: the seasonal strategy's Sharpe is
  **0.676 versus buy-and-hold's 0.771**. The strategy holds cash half the year
  (50.1% time-in-market); its lower volatility and drawdown are *reduced exposure*,
  not reward-per-unit-risk. The same risk budget applied to a sized-down
  buy-and-hold would match it. Lower risk is not alpha.

- **Crypto time-series momentum (T33).** A long-flat trend rule earns a gross
  **+79.8%/yr** — a number that sells courses. But its Sharpe is **0.79 versus
  buy-and-hold BTC's 0.99** (and −93% vs −77% max drawdown), and a *random-timing*
  placebo with matched market exposure earns **+72.8%/yr — about 91% of the
  return**. The after-cost primary t is 1.79 (< 2). The OOS sign-stability that
  the rule passes is just persistent bull-market beta. The +79.8% is levered, timed
  beta, not alpha.

- **Crypto perpetual funding carry (T29).** This is the most instructive case in
  the class, because the decomposition names the mechanism exactly. The top-decile
  funding yield is a gorgeous, real **+31.6%/yr gross**, precisely as the "retail
  crowds longs → pays the short" mechanism predicts. But under a delta-neutral book
  the **short-perp price leg gives back −25.7%/yr** — the tokens paying the most
  funding are the ones whose price tends to rise, because the crowding longs are
  *directionally right* often enough. That price loss eats ~81% of the funding; the
  thin residual is then fully consumed by ~8.5%/yr of taker friction, landing the
  net at **−2.6%/yr (t = −0.05)**, with the gross signal flipping +18 → −19 bps/day
  IS→OOS. The funding "dominating" the decomposition is not a pass — it dominates a
  return that nets to zero. You are paid to warehouse the directional risk the crowd
  is taking; that is a risk premium, not free carry. (Notably, survivorship was
  handled honestly here via Binance's append-only archive, which retains 23% delisted
  symbols — and the survivor-only re-run was essentially identical, so the kill is
  real, not a survivor mirage.)

- **Earnings-announcement premium (T43).** Real but uninvestable: a genuine +0.34%
  gross announcement effect (placebo ~0, survives the same-stock baseline at t = 2.17)
  that is only +0.24% after cost (t = 1.85, below the bar), has decayed from +0.46%
  (t = 2.76) in 2015–2020 to −0.01% (t = −0.07) in 2021–2025, and whose realized
  premium correlates **+0.73** with event-window volatility — i.e. it is
  compensation for bearing the scheduled jump, not exploitable alpha.

A closely-related sub-pattern is the **survivorship/tail trap** (T34, stablecoin
depeg), which sits at the boundary of §4.3 and §4.7. A "buy any depeg" rule shows a
survivor-only **+3.1% (t = 3.74, 100% win rate)** — and that 100% win rate with a
hidden fat left tail is the short-vol signature the tripwire is built to flag. Put
the one major USD stablecoin that *died* (UST, −67.6%) back into the sample and the
mean is **−16.0%**; the verdict is set by a single event (N = 4). Textbook pennies
in front of a steamroller, with the steamroller in the data.

**The unifying lesson of §4.7:** the gate steps that catch §4.1–§4.6 are necessary
but not sufficient. A strategy can pass the look-ahead audit, the provenance check,
the placebo, and even the after-cost t-test *and still be no edge* — if the
comparison is against the wrong benchmark. The defenses are risk-adjusted (not raw)
comparison versus the right buy-and-hold, exposure-matched placebos, and, where a
mechanism is claimed, a *mechanism* test: does the P&L actually track the spread it
claims to harvest? That last check is what separated the killed equity VRP
(IV−RV↔P&L correlation 0.01) from the one real survivor of this class (§6).

---

## 5. Data infrastructure

The campaign's posture was *collect-then-cancel*: while subscribed to a paid feed,
pull exactly what the planned tests require, store it, and own it forever — so that
a single month of a low-tier subscription funds a permanent local dataset rather
than a recurring bill. On a hobbyist budget (tens of dollars per month, with compute
free on owned hardware), this assembled a research stack that is unusual for a solo
effort:

- **~1B rows of QQQ 1-minute options data** (NBBO quotes), the owned core for the
  index-options and intraday-volatility tests, built from a local ThetaData/
  ThetaTerminal pipeline. Coverage floor is 2020-01; the 2020-03 COVID crash is
  fully covered, with documented vendor-side day-level holes in the May–Jul 2022
  1-minute data (recorded, not hidden — a provenance note, per gate step 8).
- **An ~85M-row single-name EOD option lake**, collected from ~15,553 accessible
  option roots on the existing low-tier plan (2020+), which unlocks the planned
  single-name vol-surface, dispersion, and put-call-parity tests without a paid
  upgrade.
- **A survivorship-aware crypto archive** built on Binance's append-only public
  archive (`data.binance.vision`), which *retains delisted symbols* — the single
  most important construction choice for any crypto study, since 23% of the sampled
  perp universe is dead. Building the delisting-honest universe *first*, before any
  strategy logic, is what let the funding-carry and momentum kills be credible
  rather than survivor mirages.
- **A 1,512-event classified catalyst catalog** with reproducible tooling, used for
  the Phase 2 catalyst-cohort studies (§4.5–§4.6).
- **A closed-end-fund NAV universe** for the special-situations track (§6), drawn
  from EDGAR 13D/13G filings plus NAV/discount data.

The honest constraints are stated plainly because they bound the claims. The
options data sits behind a *single* ThetaData tier; the crypto, EDGAR, yfinance, and
Deribit-DVOL feeds are free public APIs with their own walls (OKX public funding
history reaches back only ~3 months; Bybit is geoblocked; DVOL did not exist before
2021-03-24, putting the 2020-03 COVID crypto crash permanently out of sample; a
clean *free* programmatic announcement-date series for S&P 500 changes does not
exist, forcing a pre-registered effective−5-trading-day proxy in T39). Every such
wall is recorded in the relevant decision document. The point of cataloging them is
not modesty; it is that **a data wall is a result** — it bounds what the campaign
can and cannot falsify, and pretending otherwise is exactly the dishonesty the gate
exists to prevent.

A cross-cutting infrastructure lesson earned the hard way: every *new* universe
(crypto tokens, single-name underlyings, futures) reintroduces survivorship and
point-in-time risk — the failure mode behind several kills. The pre-registration
discipline defends the *test*; but look-ahead most often sneaks in *before* the test
runs, during data construction. The campaign's rule of thumb is to budget more
effort for clean universe construction (delisting logs, historical index membership,
continuous-contract roll) than for the strategy logic itself.

---

## 6. The two marginals

Two effects did not cleanly die. Reporting them honestly is more important than the
clean kills, because "real but not deployable" is — we will argue — the most likely
*true* state of the world, and a sharper finding than a total wipeout.

**The CEF discount/activist effect (T13, T15).** Following Saba Capital's initial
13D filings into closed-end funds produces a genuine, statistically real short-term
pop: **+1.44% at one month (t = 2.78, 65% of funds positive)**, with a *negative*
pre-run-up (so it is post-disclosure and capturable, not front-run). This is the
closest thing to an edge in the entire campaign, and it appeared exactly where the
thesis said to look — a capacity-constrained niche the giants cannot scale into,
reached through SEC filings. But it does not survive deployment. At a realistic ~1%
CEF round-trip (wide spreads, thin liquidity) the +1.44% pop nets to **+0.44% with
only 48% of funds positive — a coin flip**, and is negative at a 1.5% spread. The
longer-horizon payoff (6m/12m) has a positive *mean* but a *median ≈ 0*: it is a
convex lottery carried by the minority of campaigns that resolve via
tender/liquidation at NAV, not a broad steady edge. The broad discount tilt (T15) is
similar — bounded at roughly +0.7–3.6%/yr, capacity-limited, on a two-year horizon.
The effect is real; it is just uncapturable at retail scale and frequency.

**The BTC crypto-VRP (T32).** This is the campaign's most-alive result, and the one
that most rewards the gate's strictness. Crypto 30-day implied volatility (Deribit
DVOL) systematically exceeds subsequent realized volatility — **+8.9 vol-points for
BTC, IV > RV on 73% of days** — and a short-vol proxy that harvests it earns a real,
**tail-inclusive +0.061/day (t = +5.10), net Sharpe 2.24**. Crucially, unlike the
killed equity VRP, the *mechanism* test passes decisively: the correlation between
the entry-day IV−RV spread and the realized P&L is **+0.181** (the equity VRP was
0.01), with a *monotone* quartile gradient, so the P&L genuinely tracks the premium
rather than short-gamma beta. And it survives its own catastrophes: the worst days
map 1:1 onto FTX, LUNA/UST, and the May-2021 crash, yet the short collected enough
premium in the calm beforehand (DVOL was visibly pricing 70–110 vol going in) to
absorb them — drop-worst-3 still leaves t = 6.56.

And yet it is *not* deployed, for three honest reasons. First, it is **decaying**:
in-sample (2021–2023) Sharpe 3.0 / t = 5.02, out-of-sample (2024+) t = 1.88 (below 2
on its own), and 2025-onward t ≈ 1.0 — basically flat. This is the *reverse* of the
pre-registered "young, retail-heavy, less-arbitraged market preserves the premium"
thesis: the market matured, vol-sellers arrived, and the premium is compressing.
Second, it is **single-asset** — ETH was a clean kill (OOS sign flip, after-cost
t = 0.93). Third, it is a **variance-swap-replication proxy, not a tradeable margined
options book**; real Deribit execution, wing slippage, and margin calls on a spike
would erode the modest remaining edge further, and the data wall (no DVOL before
2021-03-24) means the proxy has never been tested across a COVID-class spike.

**Why "real but not deployable" is the central finding, not a hedge.** A clean
total wipeout would invite the lazy conclusion that markets are perfectly efficient
and nothing is ever there. The two marginals refute that — these effects *exist*,
with real mechanisms (activist discount-narrowing; structural insurance demand
overpaying for convexity). What kills them is not the *absence* of an inefficiency
but the presence of exactly the frictions the efficient-markets prior predicts:
capacity limits, execution costs, decay-on-discovery, and proxy-versus-reality gaps.
That is a *sharper* and more useful map than a flat zero. It says the boundary of
accessible alpha runs precisely through "real but uncapturable," and it tells a
future researcher where to *stop* — not because nothing is there, but because what
is there cannot be deployed on accessible terms by a participant at this scale.

---

## 7. Results

This section is generated from `research/CAMPAIGN_SCOREBOARD.md` (built by
`scripts/build_campaign_scoreboard.py` from `brain/34_master_test_registry.md`);
every per-test number is traceable to a committed `research/*_decision.md` or
`brain/decisions/*` record. We report the aggregate tally first, then the
breakdown that is the paper's quantitative spine — the distribution of *how* each
apparent edge turned out to be fake — and finally the full per-test table.

### 7.1 Aggregate tally

The registry holds **51 pre-registered tests**. Of these, **40 reached a
verdict**; the remaining 11 are 2 in-flight, 8 planned, and 1 merged/folded into
an adjacent test. The verdict distribution is:

| outcome | count |
|---|---:|
| **Tested (verdict reached)** | **40** |
| &nbsp;&nbsp;— Kills | 27 |
| &nbsp;&nbsp;— No-edge | 8 |
| &nbsp;&nbsp;— Marginal / split | 3 |
| &nbsp;&nbsp;— Data-wall | 2 |
| In-flight | 2 |
| Planned | 8 |
| Merged / folded | 1 |

**37 of 40 tested families reached an outright negative verdict** (27 kill, 8
no-edge, 2 data-wall); the remaining **3 are marginal** — alive in mechanism but
not claimable as a deployable edge. The scoreboard and the committed decision
records agree on these counts: the three marginals are exactly **T13** (CEF
activist follow), **T15** (CEF broad discount tilt), and **T32** (BTC crypto-VRP),
and every other tested row carries an outright kill, no-edge, or data-wall verdict
in both sources. The two single-name rows that earlier bookkeeping had filed as
marginal — **T23** (earnings IV crush, −0.59%/event at t = −3.61) and **T25**
(25Δ skew, signal-null at t = −0.10 with an OOS sign flip) — are KILLs in both the
scoreboard and their decision docs; they mention the split-spot data bug only in
passing and are not data-walls. The newest kill, **T22** (index dispersion), is the
sharpest of the friction-scale family: the correlation risk premium is *real* (gross
vega-neutral book t = +1.98; implied average correlation 0.38 > realized 0.35), yet
crossing 26 single-name straddles at their actual quoted spreads costs **365% of the
gross edge**, so the after-cost book loses at t = −5.03, sign-stable in and out of
sample. The qualitative result is unchanged: across 40 tested families, three
marginal rows resist a clean kill — the CEF effect (T13 and T15 are two windows on
the same activist/discount mechanism) and the BTC-VRP (T32), i.e. the **two distinct
effects** of §6 — and all three are "real but undeployable."

The single merged row is not a loss of information: **T30** (spot-perp basis) is
the same cash-and-carry trade as **T29** and was folded into it to avoid
double-counting. The two data-walls are **T26** (hard-to-borrow / put-call parity,
run on the wrong — easy-to-borrow — universe, where q\* collapses to dividend
yield) and **T40** (cash-merger arb, whose completed-deal targets delist and are
purged by the free price source — inverse survivorship). We count both as tested
verdicts, not as padding, because a data wall is itself a reportable result (§5),
not a non-result. Note that **T06** (intraday QQQ "Sharpe 11") is a **KILL**, not
a data-wall: its series was put-call-parity-*derived* fake data, an artifact-class
failure, not an inaccessible-data wall.

### 7.2 By artifact class — the quantitative spine

The central empirical claim of the campaign is that *every* statistically
promising result decomposed into one of a small number of named failure modes
(§4). The table below assigns each tested outcome its **primary** artifact class.
Because real kills frequently carry a second contributing class (a friction-scale
signal that is *also* short-vol beta; a decayed effect that is *also*
placebo-absorbed), the secondary-class column is tracked separately and does not
sum to the total.

| primary artifact class | tested outcomes | representative cases |
|---|---:|---|
| Look-ahead leakage | 1 | T07 (PEAD CAR[+1,+21] = −3.70%, sign-flipped) |
| Friction-scale noise | 7 | T04, T31, T23, T24, T25, T41, T22 |
| Data glitch | 1 | T16 (224% Tiingo CEF row; median ≈ 0) |
| Derived / fake data | 1 | T06 (parity-derived "Sharpe 11") |
| Pooled-baseline contamination | 1 | T17 (+2.39% mega-cap-beta baseline) |
| Composition + classifier-hindsight | 1 | T18 (matched net +0.14%, perm p = 0.47) |
| Compensated-risk / beta-in-disguise | 6 | T19, T14, T29, T33, T43, T49 |
| Survivorship / tail trap | 1 | T34 (UST −67.6% flips +3.1% → −16.0%) |
| Decay / in-noise | 8 | T12, T39, T42, T44, T45, T47, T48, T50 |
| *(subtotal — kills)* | **27** | |
| No-edge (failed at the early lab, in-noise) | 8 | T01, T02, T03, T05, T08, T09, T10, T11 |
| Data-wall | 2 | T26 (q* = dividend yield), T40 (inverse survivorship) |
| **Marginal — real but undeployable** | **3** | T13, T15, T32 |
| *(total tested rows)* | **40** | *(27 kill + 8 no-edge + 2 data-wall + 3 marginal)* |

The most-contaminated kills carry a documented second class: T39 (decay **+**
pooled-baseline, placebo +0.41% at t = 2.85), T41 (friction-scale **+** a
crypto-trust data glitch in the tail), T29 (compensated-risk **+** friction
exhausting the residual), T44 (decay **+** survivorship that biases the survivors
*up*, making the kill conservative), T45 (decay **+** composition from the high-beta
manager book), T34 (survivorship **+** the separately-fixed ms→µs epoch glitch),
and T16 (data-glitch **+** sector-drift survivorship). The pattern is the paper's
thesis in miniature: an "edge" is almost never one clean mistake; it is a stack of
two or three, any one of which is disqualifying.

Two structural observations from this distribution. First, the two **largest**
primary buckets — *decay/in-noise* (8) and *compensated-risk/beta* (6) — are
precisely the classes a conventional deflated-Sharpe screen handles worst: a
decayed anomaly still prints a positive in-sample t, and a compensated-risk
strategy is genuinely positive-expectancy yet earns nothing per unit of risk
borne. These are not "bugs in the backtest"; they are correct measurements of the
*wrong quantity*. Second, the classic *construction* artifacts (look-ahead,
data-glitch, derived-data, pooled-baseline, composition) are individually rare —
one or two each — but together they account for **5** kills that a naive pipeline
would have reported as edges, including the campaign's two most seductive numbers
(the −319% / "Sharpe 11" fabrications, both caught by provenance/verification, not
by statistics).

### 7.3 By category

| category | tested | kills | no-edge | marginal | data-wall | in-flight | planned |
|---|---:|---:|---:|---:|---:|---:|---:|
| Index options / volatility | 5 | 1 | 4 | 0 | 0 | 0 | 0 |
| 0DTE / intraday options | 0 | 0 | 0 | 0 | 0 | 1 | 2 |
| Single-name equity options | 5 | 4 | 0 | 0 | 1 | 0 | 0 |
| Crypto | 5 | 4 | 0 | 1 | 0 | 0 | 0 |
| Futures | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| Equity events & structural flow | 11 | 9 | 1 | 0 | 1 | 0 | 1 |
| Catalyst / news | 2 | 2 | 0 | 0 | 0 | 0 | 1 |
| CEF / special situations | 3 | 1 | 0 | 2 | 0 | 1 | 0 |
| Cross-sectional / multi-asset / macro | 5 | 2 | 3 | 0 | 0 | 0 | 0 |
| Seasonality / calendar | 4 | 4 | 0 | 0 | 0 | 0 | 0 |

The negative result is **breadth-wide**, not concentrated in one asset class: the
kills span index and single-name options, crypto derivatives, equity events,
catalyst/news, CEF special situations, cross-sectional/macro signals, and four
distinct calendar anomalies. No category produced a deployable survivor; the only
non-kills (CEF, BTC-VRP) are the marginals discussed in §6.

### 7.4 Most instructive single cases

Four cases earn individual mention because each isolates a different way the
campaign's discipline changed the verdict from the one a naive run would have
recorded.

- **The −319% fabricated tail (T25).** The first run of the single-name skew
  study reported a catastrophic "worst snapshot −319% / cumulative drawdown −205
  vol-units." A 21-day cash-equity forward return *cannot* fall below −100%, so
  the number was impossible on its face — a receipt for a data error, exactly as
  the §4.3 tripwire predicts. The cause was a split/spot bug (yfinance
  split-adjusted closes mismatching the lake's unadjusted strikes). Re-running on
  the parity-anchored-spot foundation (`vol_surface_data.py`, commit `bdc1174`)
  removed the fabrication; the true worst single payout is −0.48 and the kill is
  *cleaner*, not weaker (PRIMARY long–short t = −0.10, placebo p 0.89,
  premium residual α t = −33.50 on 5,197 rows). Verification, not statistics,
  caught it.

- **The t = 51 cross-exchange dispersion that is still dead (T31).** The gross
  funding-rate dispersion between Binance and OKX is real and astonishingly
  stable — **0.58 bps per 8h, t = 51, correct sign across all 19 symbols** — the
  single most "significant" number in the entire campaign. It is also completely
  untradeable: the two-venue round trip costs ~20 bps, so the same signal nets to
  **−0.38 bps/interval (t = −33) with a 2% win rate**. The t-statistic measures
  that the spread is *there*, not that it is *harvestable*. This is the §4.2
  lesson at its most extreme.

- **The "borrow signal" that was dividend yield (T26).** The put-call-parity
  implied carry q\* looked like a short-supply / hard-to-borrow signal. The
  mechanism check showed q\* = borrow + dividend yield, and on a universe of
  easy-to-borrow mega-caps borrow ≈ 0, so **q\* *is* dividend yield**:
  corr(dividend yield, q\*) = **+0.949**, with payers (PEP +109, TXN +100, CSCO
  +87 bps/yr) in the high tail and zero-dividend names (AMD −50, TSLA −45) in the
  low tail. The "implied borrow" ranking was a dividend/factor tilt wearing a
  borrow label — a confounded-label data-wall, cleanly documented rather than
  papered over.

- **BTC-VRP, the lone mechanism-real marginal (T32).** Of every tested family,
  exactly one short-vol effect passed the *mechanism* gate the equity VRP kill
  taught the campaign to require: the correlation between the entry-day IV−RV
  spread and realized P&L is **+0.181** with a monotone quartile gradient (the
  equity VRP was 0.01), tail-inclusive net t = **+5.10**, surviving FTX/LUNA/May-2021
  because DVOL was visibly pricing 70–110 vol going in. It is still not deployed —
  decaying (IS t = 5.02 → OOS t = 1.88 → 2025-onward t ≈ 1.0), single-asset (ETH
  is a clean OOS-sign-flip kill), and a variance-swap-replication proxy rather than
  a margined options book — but it is the sharpest evidence the campaign produced
  that the boundary of accessible alpha runs through "real but undeployable," not
  through "nothing is there."

### 7.5 The full per-test table

Verdicts and one-line killing reasons, grouped by category. Numbers are the
load-bearing figures from each `*_decision.md`; "→" denotes an in-sample →
out-of-sample transition.

**Index options / volatility (QQQ, owned data)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T01 | Intraday iron-condor sweep (SPY) | no-edge | early-lab **plumbing smoke**, not a gated run: a 5-day SPY 72-config sweep where every *trade-producing* config lost (least-bad 3 trades, 0% win, −$154). Validated the harness; not an OOS/gated verdict like T19–T50 |
| T02 | Iron-condor cross-regime | no-edge | wins small, loses big; 2022 realistic −$42/25 trades |
| T03 | QQQ option features (GEX, vol-of-vol, 25Δ skew, term) | no-edge | nothing survived friction + OOS |
| T09 | QQQ options microstructure (spread/depth/large quotes) | no-edge | nothing actionable after costs |
| T19 | VRP daily iron condor (signed pre-reg) | KILL | exp −$5.96 (t = −0.55); IV−RV↔P&L corr = 0.01 → mechanism null |

**Single-name equity options (EOD lake, owned)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T22 | Index dispersion / correlation premium | KILL | premium real (implied ρ 0.38 > realized ρ 0.35; gross book t = +1.98) but 26 single-name straddle spreads = 365% of the gross edge → after-cost −14%/mo (t = −5.03), OOS-stable, incremental-α t = −5.47; N = 53 |
| T23 | Single-name earnings IV crush | KILL | crush gap +1.59% real but short straddle −0.59%/event (t = −3.61) after honest bid/ask; corr(P&L, move) = −0.84 = compensated jump variance; N = 414 |
| T24 | Single-name vol term-structure carry | KILL | vega-neutral calendar −2.73/period (t = −3.41); zero alpha over short-vol book (residual t = −0.18); placebo p = 1.000 |
| T25 | Single-name 25Δ skew dynamics | KILL | skew real (+3.37 vol-pts, 90.7% of days) but signal-null −0.05%/wk (t = −0.10), OOS sign-flip, placebo p = 0.89; premium = disguised short-vol+short-delta (residual t = −33.50) |
| T26 | Hard-to-borrow / put-call-parity | data-wall | easy-to-borrow universe → q\* = dividend yield (corr +0.949), not short supply; spread +0.57% (t = +0.64) ≈ placebo |

**Crypto (free exchange APIs, survivorship-aware archive)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T29 | Perp funding carry, cross-sectional alt tail | KILL | after-cost −2.6%/yr (t = −0.05); +31.6%/yr funding ~81% repaid by short-leg price (−25.7%/yr) + fees; +18 → −19 bps/day; survivor-only ≈ cohort (not a mirage) |
| T30 | Spot-perp basis | merged | basis ≈ funding (same cash-and-carry); folded into T29 |
| T31 | Cross-exchange funding dispersion (Binance vs OKX) | KILL | gross 0.58 bps/8h (t = 51, all 19 symbols) but ≪ 20 bps round trip → −0.38 bps/interval (t = −33), 2% win |
| T32 | Crypto VRP (Deribit DVOL) | marginal | BTC mechanism real (corr +0.18, monotone, t = +5.10) but decaying (OOS t = 1.88 → ~1.0) + proxy; ETH OOS-flip kill |
| T33 | Crypto time-series momentum | KILL | +79.8%/yr but Sharpe 0.79 < B&H BTC 0.99; random-timing placebo earns ~91%; after-cost t = 1.79 → levered/timed beta |
| T34 | Stablecoin depeg mean-reversion | KILL | survivor-only +3.1% (t = 3.74, 100% win) → −16.0% once UST (−67.6%) is in; N = 4 |

**Equity events & structural flow (free EDGAR + yfinance)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T07 | PEAD | KILL | look-ahead: CAR included day-0; fixed CAR[+1,+21] = −3.70%, sign-flipped |
| T08 | 8-K item-type study | no-edge | no item category beat noise |
| T12 | IPO lock-up expiry | KILL | classic Field-Hanka effect fully decayed; CAR insignificant |
| T14 | SPAC trust arb | KILL | premium below T-bills |
| T39 | Index reconstitution / "index effect" | KILL | add CAR +0.48% (t = 1.11, median < 0); same-name placebo +0.41% (t = 2.85) → name drift, not flow |
| T40 | Cash-merger arb spread | data-wall | completed-deal targets delist & yfinance purges them (2/24 priceable, ~100% true purge); inverse survivorship |
| T41 | Buyback-announcement drift (8-K 8.01) | KILL | passes full gate (+1.08%, t = +3.39) but 64% sub-$10M/day; tiered cost −0.97%; tradeable slice +0.21% (t = +0.32), IS +3.29% → OOS −0.64% |
| T42 | Spin-off post-event drift (10-12B) | KILL | spinco 1-mo CAR −0.07% gross / −0.27% net (t = −0.03), N = 104; pooled placebo clean ~0 → genuine null |
| T43 | Earnings-announcement premium | KILL | +0.34% gross / +0.24% net (t = 1.85, < 2); +0.46% (t = 2.76) → −0.01% (t = −0.07); corr(premium, vol) = +0.73 → compensated jump |
| T44 | Insider cluster buying (Form 4, ≥2/30d) | KILL | forward CAR negative −1.86% (t = −0.83) at 3m; IS +0.34% → OOS −3.82%; survivorship biases survivors up → kill conservative |
| T45 | 13F institutional cloning (filing-date) | KILL | after-cost −0.56% at 3m (t = −2.09); loses to same-name placebo (+0.33%); IS +1.32% → OOS −2.54%; 47-day mean filing lag is the killer |

**Catalyst / news (owned classified catalog)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T17 | News catalog Phase 2 (27 cohorts) | KILL | pooled baseline +2.39% (mega-cap beta); up/down same-sign in 11 of 13 categories; 4 of 5 "survivors" within ~1% of baseline |
| T18 | product_news matched-control | KILL | raw +9.26% → matched (ticker, year) net +0.14% (t = +0.07), perm p = 0.473; cohort 23/48 TSLA, 24/48 in 2020 |

**CEF / special situations (free + cheap Tiingo)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T13 | CEF activist follow (Saba 13D) | marginal | +1.44% at 1m (t = 2.78, 65% pos) but nets +0.44% / 48% pos at ~1% round trip; 6m/12m median ≈ 0 (convex lottery) |
| T15 | CEF broad discount tilt | marginal | bounded +0.7–3.6%/yr, capacity-limited, 2-year horizon |
| T16 | CEF survival backtest | KILL | +10.5% mean = outliers + sector drift + a 224% data glitch; median ≈ 0 |

**Cross-sectional / multi-asset / macro (free)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T04 | Cross-sectional pairs / RV | KILL | 28 "survivors" were SPY/IVV microstructure: 2.88 bps mean vs ~5 bps friction |
| T05 | Multi-asset regime signals | no-edge | no survivor after deflated Sharpe |
| T06 | Intraday QQQ strategies | KILL | "Sharpe 11" from put-call-parity-derived minute data, not real spot (fake-data artifact, not a data wall); lab disabled |
| T10 | Small / illiquid universes | no-edge | no survivor (small-cap, REITs, BDCs, MLPs) |
| T11 | Pre-2010 SPY OOS | no-edge | candidates failed the extended window |

**Seasonality / calendar (free)**

| id | family | verdict | killing reason |
|---|---|---|---|
| T47 | FOMC pre-announcement drift (Lucca–Moench) | KILL | IS t = 2.08 → OOS t = −0.02; pooled t = 1.35 inside placebo 95th-pct \|t\| = 2.33 |
| T48 | Turn-of-month effect | KILL | +3.4 bps/day gross (t = 1.05 < placebo 1.93); IS +5.8 bps → OOS +0.8 bps |
| T49 | Sell-in-May / Halloween | KILL | winter−summer +0.48%/mo (t = 1.12); seasonal Sharpe 0.676 < B&H 0.771 → exposure reduction, not alpha |
| T50 | Day-of-week / pre-holiday | KILL | Monday effect gone & sign-reversed (t = 0.22); pre-holiday +5.3 bps (t = 0.93 < placebo 1.94), cost-eaten |

**In-flight and planned clusters.** Two tests are in-flight: **T20** (0DTE
short-premium, data backfilling) and **T21** (CEF resolution-selection, pending a
paid-Tiingo go/no-go). Eight are planned, concentrated in clusters that share
infrastructure already partly built: 0DTE (T27, T28), futures
term-structure/carry/seasonality/COT (T35–T38, the only genuinely extra-cost
cluster), the high-short-interest squeeze signal (T46), and the LLM
news-interpretation test (T51). None is expected to overturn the headline; each is
registered so the map is complete rather than selectively stopped.

**The capstone kill — T22 (index dispersion).** The last single-name vol-surface
test, and the most structurally interesting, is now landed. Selling index implied
correlation against the 26 constituents (SHORT the QQQ straddle, LONG a
vega-matched single-name basket) is the rare campaign test whose *mechanism is
real*: across 53 monthly rebalances the index's implied average correlation (0.38)
sits above the subsequently-realized correlation (0.35), and a frictionless,
vega-neutral dispersion book earns a marginally-significant +5.4% of index premium
per month (t = +1.98, win 58%). It does not survive the order book. Charging the
*actual* quoted half-spreads on 26 single-name straddles, crossed at entry and exit,
costs **3.65× the gross edge**, turning the book into a −14%/month, t = −5.03 loser
that is sign-stable in and out of sample (IS t = −3.36, OOS t = −3.73) and adds
negative incremental alpha over a plain short-index-vol stance (t = −5.47). It is a
friction-scale kill (class #2) — not crash compensation, since corr(return, index
move) is only +0.03. The honest qualifier: the basket is a 26-name **equal-weighted
proxy** for the Nasdaq-100 (no MSFT, equal not cap weights), so the correlation
numbers describe the mega-cap subset, and the kill speaks to the *retail,
EOD-marked, single-name-spread* version of dispersion — not to an institutional desk
with internalized flow, maker rebates, or a cap-faithful basket. With T22 down,
every tested verdict in this section is final; none is provisional.

### 7.6 Threats to validity and the scope of the claim

**What is and is not supported.** The supported claim is deliberately narrow: *no
edge survived testing and cleared deployment in the daily-frequency, liquid,
single-underlying-heavy, free/retail-data slice this campaign sampled.* The broader
statement — "the accessible space is efficient" — is a conjecture the evidence is
consistent with but does not establish. The falsification gate *passed* exactly one
family on its full signed pre-registration (BTC-VRP, T32, tail-inclusive t ≈ +5.1,
OOS sign-stable, mechanism corr +0.18); deployment was then *separately declined* on
forward-risk grounds (decay trajectory, single-asset concentration, proxy-vs-margined
book). Read "no edge survived" everywhere as "no edge survived **and cleared
deployment**."

**Multiple testing does not threaten a null.** Roughly 40 tests at a per-test |t| ≥ 2
bar would, under a global null, throw ≈2 chance survivors. The campaign found three
marginals and killed all three on grounds *orthogonal* to the gate t-statistic.
Multiplicity can only manufacture spurious *survivors* — it cannot produce a
zero-deployable-survivor conclusion; if anything it biases the result toward looking
*better* than it is, the conservative direction for a negative claim. (The one
surviving per-test t-statistic that would not clear a family-wise threshold, T13 at
t = 2.78, is demoted on friction, not significance, so nothing turns on the
uncorrected bar.)

**Power — not false discovery — is the dominant risk, by design.** A null result's
real exposure is Type-II error: a small, real, deployable edge the gate missed. The
gate is a seven-way AND (pre-registration, N ≥ 30, after-cost |t| ≥ 2, OOS
sign-stability, baseline-net, matched-control permutation, provenance), and
conjunctions compound Type-II error. We own this and hold it is the *correct*
operating point: under the campaign's asymmetric loss function a false negative costs
$0 (you simply do not trade) while a false positive costs real capital, so a
high-Type-II / low-Type-I gate is the right tool, and the AND-stack is its deliberate
mechanism. The gate is demonstrably not pathologically over-killing — it passed
BTC-VRP through to a mechanism-positive t ≈ +5 and let the CEF pop register at
t ≈ +2.8. For the well-powered mass of the campaign (the N > 1000 event studies,
where |t| ≥ 2 detects effects of a few bps) "no edge" provably means "no edge large
enough to matter"; the genuinely low-N tests (T34 at N = 4; the single-name N ≈ 53
studies) are under-powered for small effects, and their kills rest on the *direction*
and *magnitude* of the after-cost loss (T22 nets to t = −5.0; T34 flips to −16% once
the one dead stablecoin re-enters), which underpower cannot fake — not on a confident
zero.

**Scope limits we do not claim past.** (a) Despite ~1B rows of minute data, *zero*
intraday-execution tests closed (T06 died on fabricated data; the 0DTE cluster is
unfinished), so nothing here extends to sub-daily holding periods — and the
efficient-markets prior makes that untested corner the *most* plausible place a
survivor could still hide. (b) The "yfinance purges delisted names → survivors biased
up → a kill is conservative" argument is *directional*, not a quantified bound; the
kills are valid for the surviving liquid subsample and explicitly do not falsify
effects in the purged small-cap tail. (c) This is a *convenience sample* —
"collect-then-cancel" biased coverage toward daily-bar event studies and options on
owned underlyings and *away from* options market-making/liquidity provision (the
campaign only ever *pays* the spread — T04, T22, T31 — never *captures* it), intraday
stat-arb, cross-asset/futures carry, and ML/alt-data.

A fuller, threat-by-threat treatment — including the q = 0 parity-spot robustness
(the shift is ≈ (q·T)·S, ≲ 0.2% over ≤ 120-day tenors for the largest dividend payers,
sub-strike-increment, so the ATM selection is unchanged), the per-cluster friction
schedule, and the taxonomy's 7→9 *discovery* framing — is in
[`research/THREATS_TO_VALIDITY.md`](THREATS_TO_VALIDITY.md). Positioning against the
prior academic and practitioner literature per effect family is in
[`research/RELATED_WORK.md`](RELATED_WORK.md).

---

## 8. Conclusion

### 8.1 The thesis, now evidenced

The campaign set out to answer one question honestly: does *any* edge accessible
to a solo researcher on free, retail-grade data survive a test designed to kill
it? Across **39 pre-registered families that reached a verdict** — spanning index
and single-name options, crypto derivatives, equity events and structural flow,
catalyst-driven news, closed-end-fund special situations, cross-sectional/macro
signals, and four calendar anomalies — the answer is **no deployable edge
survived**. Thirty-six of the thirty-nine reached an outright negative verdict;
the apparent survivors, without exception, decomposed under scrutiny into the
named failure modes of §4. The two largest buckets are the most telling:
*decay-into-noise* and *compensated-risk/beta-in-disguise* together account for
the bulk of the kills, and both are classes a conventional deflated-Sharpe screen
passes — a decayed anomaly still prints a positive in-sample t, and a
compensated-risk strategy is genuinely positive-expectancy yet earns nothing per
unit of risk borne. The campaign's value is precisely that it caught what the
standard screen does not.

The famous published anomalies fared exactly as the post-publication literature
predicts. The pre-FOMC drift (IS t = 2.08 → OOS t = −0.02), the turn-of-month
effect (IS +5.8 bps → OOS +0.8 bps), sell-in-May (a Sharpe *below* buy-and-hold),
the index-reconstitution effect (placebo-absorbed), PEAD (a look-ahead artifact),
the spin-off and IPO-lockup premia, insider-cluster following, and 13F cloning —
each was real once and is gone now, on free data, today. That a published anomaly
has decayed into the placebo band is a *finding*, and the campaign reports nine of
them.

### 8.2 The sharper finding: real but undeployable

A clean total wipeout would invite the lazy reading that markets are perfectly
efficient and nothing is ever there. The three genuine marginals refute that, and
they are the most important result in the paper. The **CEF activist/discount
effect** (T13/T15) is real — Saba's 13D filings produce a +1.44% one-month pop
(t = 2.78, 65% positive) with a negative pre-run-up, exactly where the thesis said
to look — but it nets to a coin flip (+0.44%, 48% positive) at a realistic ~1% CEF
round trip, and its longer-horizon payoff is a convex lottery with a median near
zero. The **BTC crypto-VRP** (T32) is the campaign's most-alive result and the one
that most rewards the gate's strictness: it passes the *mechanism* test the equity
VRP failed (spread↔P&L corr +0.181 vs 0.01, monotone gradient, tail-inclusive
t = +5.10), yet it is decaying out (OOS t = 1.88 → ~1.0), single-asset (ETH is a
clean kill), and a variance-swap-replication proxy rather than a margined book.

What kills these is *not* the absence of an inefficiency — it is the presence of
exactly the frictions the efficient-markets prior predicts: capacity limits,
execution costs, decay-on-discovery, and proxy-versus-reality gaps. That is a
sharper and more useful map than a flat zero. It locates the boundary of
accessible alpha precisely at "real but uncapturable," and it tells a future
researcher where to *stop* — not because nothing is there, but because what is
there cannot be deployed on accessible terms at this scale.

### 8.3 What the campaign actually produced

The contribution is not an edge; it is the apparatus that proved there wasn't one,
and that apparatus is reusable.

- **A falsification machine.** The eight-step gate (§3), with its numeric core
  codified as a single shared, pure *reference* evaluator
  (`src/trader/research/gate.py`) whose pre-registration and provenance flags
  *default to False*, so a forgetful caller fails rather than silently passes (the
  per-test gates share its conventions and are audited against it — see §3 for the
  one documented divergence). It caught at least seven distinct
  classes of false positive — several of which a deflated-Sharpe screen waves
  through — and it caught the two most seductive numbers in the campaign (the
  "Sharpe 11" and the −319% tail) by *provenance and verification*, not by
  statistics.
- **An artifact taxonomy** (§4) illustrated end-to-end with the campaign's own
  real numbers — the empirical distribution of *how* apparent edges on accessible
  data turn out to be fake, against which a future claimant can locate and rule
  out their own would-be edge.
- **The data infrastructure** (§5): ~1B rows of QQQ 1-minute options, an ~85M-row
  single-name EOD option lake, a survivorship-aware crypto archive that retains
  delisted symbols, a 1,512-event classified catalyst catalog, and a CEF NAV
  universe — assembled on a hobbyist budget under a collect-then-cancel posture, so
  a month of low-tier subscription funds a permanent owned dataset.
- **The discipline itself**: ~50 pre-registrations, decision records with verdicts
  and artifact-class labels, and a registry that composes mechanically into this
  paper. The negative result is decision-grade *because* the process that produced
  it is auditable.

### 8.4 Honest limitations

The claims are bounded by the data, and the bounds are stated plainly because
pretending otherwise is the dishonesty the gate exists to prevent. The options
data sits behind a *single* ThetaData tier. The crypto, EDGAR, yfinance, and
Deribit-DVOL feeds are free public APIs with hard walls — OKX public funding
reaches back ~3 months, Bybit is geoblocked, DVOL did not exist before 2021-03-24
(so the 2020-03 COVID crash is permanently out of the crypto-VRP sample), and no
free programmatic announcement-date series exists for S&P 500 changes. Two tested
families reached a data-wall verdict (T26 hard-to-borrow / put-call parity, T40
cash-merger arb) — both live in exactly the population — delisted targets,
hard-to-borrow small caps — that the free price source either purges or never
contained. The campaign has **no broad survivorship-free equity panel**: the
EDGAR + yfinance event studies repeatedly lost 40–80% of their universe to
yfinance's delisting purge (conservatively, since the purge biases survivors *up*),
and a clean CRSP-grade panel would be needed to test the neglected small-cap tail
where several of these anomalies historically lived. The storage and compute
constraints of a solo effort cap the frequency and breadth of what can be held and
re-run. Extending the campaign would mean, in order of leverage: a delisted-retaining
price source (Tiingo/CRSP), a true intraday options book for the proxy-limited
vol tests, and a funded futures vendor for the one untested asset class (T35–T38).

### 8.5 Closing

The efficient-markets prior held. On the most-arbitraged corner of finance —
liquid, public, mostly daily-frequency US instruments reached through free data —
a solo researcher found no edge that survives honest testing, and the few effects
that are *real* are not *deployable*. The honest forward posture follows directly:
an index core, rare high-conviction defined-risk bets, and a machine that kills bad
ideas before they cost money. The value of this work is not a strategy. It is the
rigor with which the absence of one was established, the named explanation for each
mirage, and the reusable apparatus — gate, taxonomy, and data — that makes the next
researcher's due diligence cheaper than ours was. A credible map of where the edges
are *not*, with a tested reason for each absence, is rarer than an edge — and, we
have argued, more durable.

---

*Appendix pointers (for the eventual full version): per-test pre-registrations and
decision records live under `research/*_preregistration.md` and
`research/*_decision.md`; consolidated narrative and the original 7-class taxonomy
in `brain/30_campaign_findings.md`; the test registry and category map in
`brain/34_master_test_registry.md`; the shared gate in
`src/trader/research/gate.py`.*
