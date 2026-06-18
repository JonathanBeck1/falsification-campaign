# Does Any Accessible Edge Survive Rigorous Testing?

**A pre-registered falsification campaign across ~50 strategy families — and the negative result it produced.**

One researcher, a hobbyist budget, and free or retail-accessible market data. Fifty-one *genuinely distinct* strategy families — index and single-name options, crypto derivatives, equity events and structural flow, catalyst-driven news, closed-end-fund special situations, cross-sectional/macro signals, and calendar seasonality — were pre-registered against a single fixed eight-step gate designed to *kill* them. Forty reached a verdict. **No deployable edge survived.** Thirty-seven of the forty reached an outright negative verdict; the three that resisted a clean kill were real in mechanism but uncapturable at retail scale. Every statistically promising result, without exception, decomposed under scrutiny into one of a small number of recurring failure modes.

This repository is **not a trading strategy**. It is the apparatus that proved there wasn't one, the documented negative result, and the taxonomy that explains *why* each apparent edge was a mirage.

> ⚠️ **Informational research only. Not investment advice. Not a trading bot.** See [What this is / isn't](#what-this-is--isnt).

---

## Headline tally

| Outcome | Count |
|---|---:|
| **Tested (verdict reached)** | **40** |
| &nbsp;&nbsp;— Kills | 27 |
| &nbsp;&nbsp;— No-edge | 8 |
| &nbsp;&nbsp;— Marginal / split (real but undeployable) | 3 |
| &nbsp;&nbsp;— Data-wall | 2 |
| In-flight | 2 |
| Planned | 8 |
| Merged / folded | 1 |
| **Total in registry** | **51** |

**37 of 40 tested families reached an outright negative verdict** (27 kill + 8 no-edge + 2 data-wall). The 3 marginals — the closed-end-fund activist/discount effect and the BTC crypto volatility-risk premium — are alive in mechanism yet not deployable: capacity-limited and execution-eaten, or decaying and proxy-not-tradeable.

The two largest kill buckets — *decay-into-noise* (8) and *compensated-risk / beta-in-disguise* (6) — are precisely the classes a conventional deflated-Sharpe screen passes. That is the point: the campaign caught what the standard screen does not.

📄 **Read the full paper:** [`research/PAPER_DRAFT.md`](research/PAPER_DRAFT.md)

---

## The contribution

The value here is not an edge. It is three durable things:

1. **A falsification machine.** A single fixed eight-step gate, with its numeric core codified as a shared, unit-tested reference evaluator ([`src/trader/research/gate.py`](src/trader/research/gate.py)), whose pre-registration and provenance acknowledgement flags **default to `False`** — so a forgetful caller *fails* the gate rather than silently passing it. It catches at least seven distinct classes of false positive, several of which a deflated-Sharpe screen waves through.

2. **An artifact taxonomy.** The empirical distribution of *how* apparent edges on accessible data turn out to be fake — illustrated end-to-end with the campaign's own real numbers. A future claimant who can name which class their would-be edge most resembles, and show it doesn't apply, has done most of the work of due diligence. ([`brain/30_campaign_findings.md`](brain/30_campaign_findings.md))

3. **The documented negative result + data infrastructure.** ~50 pre-registrations, decision records with verdicts and artifact-class labels, and a registry that composes mechanically into the paper — assembled honestly on a hobbyist budget.

---

## Methodology

### Pre-registration

The hypothesis, cohort definition, measurement windows, the sample-size (N) arithmetic, and the explicit kill criteria are written and committed **before any result exists** — removing the single largest source of overfitting: specification search after seeing the data. Every test has a committed `research/*_preregistration.md`.

### The universal gate (8 steps, no exceptions)

Every test passed through the same ordered gate before any result could be written down. A test that skips a step is not "done." Each step exists to catch a specific class of false positive the campaign actually encountered.

| # | Step | What it catches |
|---|---|---|
| 1 | **Pre-registration** | Post-hoc specification search |
| 2 | **Friction realism** | Signals real in basis points but smaller than round-trip cost. *After-cost* expectancy is the **only** metric ever ranked or filtered on. |
| 3 | **Look-ahead audit** | The event that *defines* a cohort leaking into the window that *measures* its return |
| 4 | **OOS sign stability** | Mined effects that flip sign out-of-sample (early/late split, same sign, both halves N ≥ 10) |
| 5 | **Pooled baseline** | A cohort inheriting the drift/beta of its universe (with an up/down symmetry check) |
| 6 | **Matched-control permutation** | A cohort that *clusters* in high-drift (ticker, year) cells — requires permutation *p* < 0.05 **and** net \|t\| ≥ 2 |
| 7 | **Too-good-to-be-true tripwire** | Sharpe > 3, win rate > 85%, or a median far from the mean → auto-triggers a placebo run + by-hand top-contributor inspection (robust MAD-based, so outliers can't hide in inflated σ) |
| 8 | **Data provenance** | Data errors masquerading as alpha — derived/stale series, vendor glitches, epoch-unit corruption |

**Implementation honesty.** The numeric core (one-sample t with `ddof=1` against null 0; after-cost mean; OOS same-sign split; one-sided permutation; the Sharpe/win-rate/MAD-gap tripwire) is codified as a single pure reference evaluator, `evaluate_gate(...)`, pinned by [`tests/financial/test_research_gate.py`](tests/financial/test_research_gate.py). Most per-test modules *re-implement* this core in their own `evaluate_gate`, sharing the reference's conventions rather than its code. An adversarial code review found a few hand-rolled gates had drifted *weaker* than the reference (the insider-cluster and 13F placebo lines, the 13F/spin-off OOS N-floor, the crypto-momentum tripwire); **these have since been aligned** — the placebo lines now require a null placebo, the OOS N≥10-per-half floor is enforced in every event study's gate, and crypto momentum calls the shared `too_good_tripwire`. No verdict changed (each was already killed on other lines; the alignment only tightens the gate). The duplicated event-study plumbing and the two-sample Welch t are now consolidated into [`trader/research/event_study.py`](src/trader/research/event_study.py) and `gate.welch_t`. Full delegation of every test to `evaluate_gate` is the tracked next step.

Steps 1 and 8 cannot be inspected by a pure function (no function can read a git commit or a data-source note), so they are surfaced as acknowledgement flags that **default to `False`** — a forgetful caller fails the gate. That default is the whole point.

### Adversarial verification

The two most seductive numbers in the entire campaign — a "Sharpe 11" and a "−319%" tail — were caught by **provenance and verification, not by statistics**:

- The "Sharpe 11" intraday lab (T06) traded against a *put-call-parity-derived* "minute spot" series — i.e. against its own construction assumption. A Sharpe of 11 is never an edge; it is a receipt for a data error.
- The "−319%" single-name skew tail (T25) was impossible on its face (a 21-day cash-equity return cannot fall below −100%) — a split/spot data bug. Re-running on a parity-anchored-spot foundation removed the fabrication and made the kill *cleaner*, not weaker.

---

## The artifact taxonomy

Every kill belongs to one class. Each is illustrated below with the campaign's best real example and its actual numbers.

| Class | Canonical case | The number |
|---|---|---|
| **1. Look-ahead leakage** | PEAD (T07) | CAR included day-0; corrected CAR[+1,+21] = **−3.70%**, sign-flipped |
| **2. Friction-scale noise** | Cross-exchange funding (T31) | Gross **0.58 bps/8h, t = 51, all 19 symbols** — but ≪ 20 bps round trip → **−0.38 bps/interval (t = −33), 2% win rate** |
| **3. Data glitch** | Tiingo CEF (T16) | A **224%** single-day "return" inflated a +10.5% mean; median ≈ 0 |
| **4. Derived / fake data** | Intraday QQQ (T06) | **Sharpe 11** from parity-derived minute data, not real spot |
| **5. Pooled-baseline contamination** | News Phase 2 (T17) | Pooled baseline **+2.39%** (mega-cap beta); up/down cohorts drift the *same* sign in **11 of 13** categories |
| **6. Composition + classifier hindsight** | product_news (T18) | Raw **+9.26%** → matched (ticker, year) net **+0.14% (t = +0.07)**, permutation *p* = **0.473**; cohort was 23/48 Tesla, 24/48 in 2020 |
| **7. Compensated-risk / beta in disguise** | Funding carry (T29), trend (T33), sell-in-May (T49) | Real economic mechanism, genuinely positive expectancy — but **zero alpha per unit of risk borne** |

**Class 7 is the broadest and most important** — it is where the *honest* strategies, the ones with a real mechanism, go to die. Crypto funding carry (T29) earns a gorgeous **+31.6%/yr gross**, but the delta-neutral short-perp price leg gives back **−25.7%/yr** (the crowding longs are directionally right often enough), and taker fees consume the residual → net **−2.6%/yr (t = −0.05)**. You are paid to warehouse the crowd's directional risk. That is a risk premium, not free carry.

**The unifying lesson:** an "edge" is almost never one clean mistake; it is a stack of two or three, any one of which is disqualifying. And the gate steps that catch classes 1–6 are necessary but not sufficient — a strategy can pass the look-ahead audit, the provenance check, the placebo, and even the after-cost t-test *and still be no edge* if the comparison is against the wrong benchmark.

---

## Results (compact)

Full per-test table with killing reasons: [`research/CAMPAIGN_SCOREBOARD.md`](research/CAMPAIGN_SCOREBOARD.md) (auto-generated from the registry by `scripts/build_campaign_scoreboard.py`).

### By category

| Category | Tested | Kills | No-edge | Marginal | Data-wall | In-flight | Planned |
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

The negative result is **breadth-wide**, not concentrated in one asset class. No category produced a deployable survivor.

### The famous published anomalies fared exactly as the post-publication literature predicts

| Anomaly | Verdict |
|---|---|
| Pre-FOMC drift (Lucca–Moench) (T47) | IS t = 2.08 → **OOS t = −0.02** |
| Turn-of-month (T48) | IS +5.8 bps → **OOS +0.8 bps**, inside placebo band |
| Sell-in-May / Halloween (T49) | Seasonal Sharpe **0.68 < buy-and-hold 0.77** — exposure reduction, not alpha |
| Index-reconstitution "index effect" (T39) | Add CAR +0.48% (t = 1.11), **placebo-absorbed** (+0.41%, t = 2.85) → name drift, not flow |
| PEAD (T07) | **Look-ahead artifact** (CAR[+1,+21] = −3.70%) |
| Spin-off drift (T42), IPO-lockup (T12) | Decayed nulls |
| Insider-cluster following (T44), 13F cloning (T45) | OOS sign-flips; 47-day mean filing lag is the killer |

A published anomaly that has decayed into the placebo band is a *finding*, not a failure.

### The three marginals — *real but undeployable*

This is the **sharper finding**, not a hedge. A clean total wipeout would invite the lazy reading that markets are perfectly efficient and nothing is ever there. These effects *exist*, with real mechanisms — what kills them is exactly the frictions the efficient-markets prior predicts.

- **CEF activist/discount (T13, T15).** Following Saba Capital's 13D filings produces a genuine **+1.44% one-month pop (t = 2.78, 65% positive)** with a *negative* pre-run-up (capturable, not front-run). But at a realistic ~1% CEF round trip it nets to **+0.44% with 48% positive — a coin flip**; the longer-horizon payoff is a convex lottery with median ≈ 0. Real; uncapturable at retail scale.

- **BTC crypto-VRP (T32).** The campaign's most-alive result. Deribit DVOL exceeds subsequent realized vol by **+8.9 vol-points (IV > RV on 73% of days)**; a short-vol proxy earns tail-inclusive **+0.061/day (t = +5.10), net Sharpe 2.24**. Crucially it passes the *mechanism* test the killed equity VRP failed — spread↔P&L correlation **+0.181** (equity VRP: 0.01), monotone quartile gradient. But it is **decaying** (IS t = 5.02 → OOS t = 1.88 → 2025-onward t ≈ 1.0), **single-asset** (ETH was a clean OOS-sign-flip kill), and a **variance-swap-replication proxy**, not a margined options book.

The boundary of accessible alpha runs precisely through *"real but uncapturable"* — and that tells a future researcher where to *stop*.

---

## What this is / isn't

**This IS:**
- Informational, reproducible research — a documented negative result and the apparatus that produced it.
- A reusable falsification methodology (the gate, the taxonomy, adversarial verification) you can apply to your own would-be edge.
- An honest map of where retail-accessible alpha is *not*, with a tested explanation for each absence.
- A portfolio piece demonstrating research rigor: pre-registration, friction realism, look-ahead discipline, and intellectual honesty about limitations.

**This is NOT:**
- ❌ Investment advice or a recommendation to trade anything.
- ❌ A trading bot, signal service, or "alpha." The whole point is that **no deployable edge was found.**
- ❌ A claim that markets are perfectly efficient — two real mechanisms *were* found; they simply aren't deployable on accessible terms.
- ❌ A guarantee of correctness. The claims are bounded by the data, and those bounds are stated plainly (see [Limitations](#honest-limitations)).

Nothing here should be the final unchecked authority for live trades. Do your own research.

---

## Repository map

| Path | Contents |
|---|---|
| [`research/PAPER_DRAFT.md`](research/PAPER_DRAFT.md) | **The full paper** — abstract, methodology, taxonomy, results, conclusion. Start here. |
| [`research/CAMPAIGN_SCOREBOARD.md`](research/CAMPAIGN_SCOREBOARD.md) | Auto-generated master results table (the paper's §7). |
| `research/*_preregistration.md` | Per-test pre-registrations (hypothesis, cohort, windows, N, kill criteria) — committed *before* results. |
| `research/*_decision.md` | Per-test decision records — verdict, load-bearing numbers, artifact class. |
| [`brain/30_campaign_findings.md`](brain/30_campaign_findings.md) | The consolidated narrative + original 7-class artifact taxonomy. |
| [`brain/34_master_test_registry.md`](brain/34_master_test_registry.md) | The 51-test registry / table of contents — the source of truth the scoreboard is built from. |
| [`src/trader/research/gate.py`](src/trader/research/gate.py) | The shared reference gate evaluator (the numeric core of the 8-step gate). |
| `tests/financial/` | The test suite (1,800+ financial tests), including `test_research_gate.py` which pins the gate. |
| `scripts/run_*_study.py` | One runnable study per family (e.g. `run_crypto_vrp_study.py`, `run_earnings_premium_study.py`). |
| `scripts/build_campaign_scoreboard.py` | Regenerates the scoreboard from the registry. |
| `brain/` | The full research-log / decision history of the campaign. |

---

## Data provenance & reproducibility

The campaign's posture was **collect-then-cancel**: while subscribed to a paid feed, pull exactly what the planned tests require, store it, and own it forever — so a single month of a low-tier subscription funds a permanent local dataset rather than a recurring bill. On a hobbyist budget (tens of dollars per month, compute free on owned hardware) this assembled an unusual stack for a solo effort:

- **~1B rows of QQQ 1-minute options NBBO quotes** — the owned core for index-options and intraday-volatility tests, built from a local ThetaData / ThetaTerminal pipeline (coverage floor 2020-01; the 2020-03 COVID crash is fully covered, with documented vendor-side day-holes in May–Jul 2022, recorded not hidden).
- **An ~85M-row single-name EOD option lake** — collected from ~15,553 accessible option roots on a low-tier ThetaData plan (2020+).
- **A survivorship-aware crypto archive** built on Binance's append-only public archive (`data.binance.vision`), which **retains delisted symbols** — 23% of the sampled perp universe is dead. Building the delisting-honest universe *first* is what made the funding and momentum kills credible rather than survivor mirages.
- **A 1,512-event classified catalyst catalog** with reproducible tooling.
- **A closed-end-fund NAV universe** drawn from EDGAR 13D/13G filings plus NAV/discount data.

### What is NOT included in this repository

> The large and/or **licensed datasets are not committed.** The `data/` directory and large outputs are git-ignored. Specifically **excluded**:
>
> - **ThetaData** options data (the ~1B-row QQQ 1-minute quotes and the ~85M-row single-name EOD lake) — licensed vendor data; redistribution is not permitted.
> - **Tiingo** CEF NAV/price series — licensed.
> - Any API keys or `.env` secrets (`.env.example` shows the required variables).

What **is** committed: the full code, every pre-registration and decision record, the registry, the scoreboard, the gate, the test suite, and small derived result artifacts sufficient to follow each verdict's arithmetic.

### Re-collecting the data

The pipelines to rebuild the datasets are in the repo:

- **Options (ThetaData):** stand up ThetaTerminal with your own ThetaData subscription; the adapters under `src/trader/adapters/thetadata/` and the collection scripts pull the QQQ 1-minute quotes and the single-name EOD basket. (The low-tier plan is sufficient for the single-name lake; see the registry for the verified ~15,553 accessible roots.)
- **Crypto (free):** `data.binance.vision` (survivorship-aware), Deribit DVOL, and exchange public APIs — no subscription required. Note the documented walls: OKX public funding history reaches back ~3 months, Bybit is geoblocked, and DVOL did not exist before 2021-03-24.
- **Equity events (free):** EDGAR filings + yfinance prices. Note yfinance's delisting purge biases survivors *up* — see the data-wall verdicts (T26, T40).
- **Catalyst catalog & CEF (free + cheap Tiingo):** `scripts/build_cef_universe.py`, `scripts/catalog_orchestrate.py`, and related tooling.

Each `research/*_preregistration.md` documents the exact data its test consumes, and each study has a corresponding `scripts/run_*_study.py`.

---

## Honest limitations

Stated plainly, because pretending otherwise is the dishonesty the gate exists to prevent:

- The options data sits behind a **single** ThetaData tier.
- The crypto, EDGAR, yfinance, and Deribit-DVOL feeds are free public APIs with hard walls (OKX ~3-month funding history; Bybit geoblocked; DVOL absent before 2021-03-24, so the 2020-03 COVID crash is permanently out of the crypto-VRP sample; no free programmatic announcement-date series for S&P 500 changes).
- **A data wall is a result.** Two tested families (T26 hard-to-borrow / put-call parity, T40 cash-merger arb) reached a data-wall verdict — both live in exactly the population the free price source purges or never contained.
- The campaign has **no broad survivorship-free equity panel.** The EDGAR + yfinance event studies repeatedly lost 40–80% of their universe to yfinance's delisting purge (conservatively — the purge biases survivors up). A CRSP-grade panel would be needed for the neglected small-cap tail.
- Solo storage and compute cap the frequency and breadth of what can be held and re-run.

Highest-leverage extensions, in order: a delisted-retaining price source (Tiingo / CRSP), a true intraday options book for the proxy-limited vol tests, and a funded futures vendor for the one untested asset class (T35–T38).

---

## Closing

The efficient-markets prior held. On the most-arbitraged corner of finance — liquid, public, mostly daily-frequency US instruments reached through free data — a solo researcher found **no edge that survives honest testing**, and the few effects that are *real* are not *deployable*.

The value of this work is not a strategy. It is the rigor with which the absence of one was established, the named explanation for each mirage, and the reusable apparatus — gate, taxonomy, and data — that makes the next researcher's due diligence cheaper than ours was. A credible map of where the edges are *not*, with a tested reason for each absence, is rarer than an edge — and, we argue, more durable.

**→ Read the full paper: [`research/PAPER_DRAFT.md`](research/PAPER_DRAFT.md)**

---

*Informational research only; not investment advice. Past results — including the negative ones documented here — do not guarantee future outcomes.*
