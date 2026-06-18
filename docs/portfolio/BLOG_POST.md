# I Spent Months Trying to Find a Trading Edge. I Found None — and That's the Point.

*A pre-registered falsification campaign across ~50 strategy families, on free and
retail-accessible data, and the apparatus that proved there was nothing there.*

---

## The short version

I set out to answer one question honestly: **does any tradeable edge survive
rigorous testing on the data a solo researcher can actually get?** I pre-registered
51 strategy families — index and single-name options, crypto derivatives, equity
events, catalyst-driven news, closed-end-fund special situations, cross-sectional
and macro signals, calendar seasonality — and ran each through a single fixed,
eight-step gate designed to *kill* it.

Forty reached a verdict. **None produced a deployable edge.** Thirty-seven were
outright negative; the three survivors were real in mechanism but uncapturable at
retail scale. And every single statistically promising result, without exception,
decomposed under scrutiny into one of a small number of recurring failure modes.

That last sentence is the whole project. The deliverable was never a strategy. It
was a *falsification machine* — and the discipline to point it at my own best
ideas and watch them die.

---

## Why a negative result is the interesting result

Anyone can produce a backtest with a great Sharpe ratio. The skill — the one that
separates a researcher who will lose a desk money from one who won't — is the
ability to look at your own beautiful equity curve and figure out why it's a lie
*before* you trade it.

A trading desk loses money on **false positives**: a mirage it deploys. It loses
nothing on **false negatives**: an edge it skips. So the correct research posture is
ruthless skepticism toward your own findings, and the correct success metric is not
"how many edges did I find" but "how many mirages did I correctly reject." By that
metric the campaign is a clean success: it rejected ~50 candidates and, more
importantly, named the *specific* reason each one was fake.

I built the whole thing around one rule I borrowed from experimental science:
**pre-registration.** For every test, the hypothesis, the cohort definition, the
measurement windows, the sample-size arithmetic, and the explicit kill criteria
were written and committed to git *before* I computed a single result. That one
constraint removes the largest source of self-deception in quant research:
searching the specification space until something looks significant.

---

## The gate: eight ways to kill an idea

Every candidate passed through the same ordered gate. A test that skipped a step
wasn't "done." Each step exists because it caught a real false positive:

1. **Pre-registration** — no post-hoc specification search.
2. **Friction realism** — after-cost expectancy is the *only* number I ever ranked
   on. A signal real in basis points but smaller than its round-trip cost is not an
   edge.
3. **Look-ahead audit** — the event that *defines* a cohort must not leak into the
   window that *measures* its return.
4. **Out-of-sample sign stability** — split early/late; a real effect keeps its
   sign, a mined one flips.
5. **Pooled baseline** — does the cohort just inherit the drift or beta of its
   universe?
6. **Matched-control permutation** — does the "edge" survive against composition-
   matched random cohorts, or is it just clustering in high-drift names/years?
7. **Too-good-to-be-true tripwire** — Sharpe > 3, win rate > 85%, or a mean dragged
   by one outlier row → auto-trigger a hand inspection.
8. **Data provenance** — is the "alpha" actually a data error: a derived series, a
   vendor glitch, a units bug?

The gate's numeric core is a single shared, unit-tested module whose
acknowledgement flags *default to false* — so a forgetful caller fails the gate
rather than silently passing it. That default is the whole philosophy in one line
of code.

---

## Three mirages, and how they died

**The "Sharpe 11."** An intraday options lab lit up with a Sharpe of 11. A Sharpe
of 11 is never an edge; it's a receipt for a data bug. This one was trading against
a "minute spot" price I had *derived from the options themselves* via put-call
parity — i.e., against its own construction assumption. Caught by **provenance**,
not statistics. No t-test would have saved me; only asking "where did this number
come from?" did.

**The −319% tail.** A single-name skew strategy reported a worst-case loss of
−319%. That's impossible on its face — a cash-equity position can't lose more than
100% — so it had to be a data bug (a stock-split/spot-scale mismatch). I rebuilt
the volatility-surface foundation on a parity-anchored spot, the fabrication
vanished, and the kill got *cleaner*, not weaker. The lesson: an impossible number
is a gift, because it's unambiguous.

**The +9.26% that became +0.14%.** A news-catalyst cohort showed a +9.26% average
move. After matching each event to composition-identical (same ticker, same year)
non-event controls, the net collapsed to **+0.14% with a permutation p-value of
0.47** — pure noise. The cohort had been 23-of-48 Tesla and 24-of-48 in 2020. It
wasn't measuring news; it was measuring "Tesla in 2020." The matched-control
permutation is the step that turns a story into a number.

---

## The pattern under every kill

The most useful output isn't the list of dead strategies; it's the **taxonomy of
how they died**. Across all 40 tests, every apparent edge fell into one of nine
classes. Two of them did most of the killing:

- **Decay-into-noise** (8 tests). The famous published anomalies — pre-FOMC drift,
  turn-of-month, the index-inclusion effect, post-earnings drift, spin-off drift —
  were *real when discovered* and have since been arbitraged into the placebo band.
  Pre-FOMC drift went from in-sample t = 2.08 to out-of-sample t = −0.02. A decayed
  anomaly is a finding, not a failure.
- **Compensated risk / beta in disguise** (6 tests). This is where the *honest*
  strategies go to die — the ones with a real economic mechanism. Crypto perpetual
  funding carry earns a gorgeous **+31.6%/yr gross**; retail crowds pile long and
  pay the short. But under a delta-neutral book, the short leg gives back
  **−25.7%/yr** (the crowd is directionally right often enough), fees eat the rest,
  and you net **−2.6%/yr**. You're being paid to warehouse the crowd's risk. That's
  a risk premium, not free alpha — and the gate's job is to tell the difference.

The unifying lesson, stated once: **an "edge" is almost never one clean mistake.
It's a stack of two or three, any one of which is disqualifying.**

---

## The sharpest result: real, but you still can't have it

A total wipeout would invite the lazy reading that markets are perfectly efficient
and nothing is ever there. The truth is more interesting. Three effects *survived*
as real mechanisms and were killed only by the frictions the efficient-markets
prior predicts:

- **Index dispersion** (the newest test). Index implied correlation genuinely runs
  above realized — the correlation risk premium is real, and a frictionless
  dispersion book earns a marginally-significant edge. But charging the *actual*
  quoted bid/ask on 26 single-name option straddles costs **365% of the gross
  edge**. The premium exists; you cannot have it at retail friction.
- **Closed-end-fund activism.** Following an activist's 13D filings earns a real
  **+1.44% one-month pop (t = 2.78)**. At a realistic ~1% round trip it nets to a
  coin flip.
- **Crypto variance risk premium.** The one family that passed the *full* gate —
  mechanism-positive, out-of-sample stable. I declined to deploy it anyway, on
  forward-risk grounds (it's decaying, single-asset, and a replication proxy rather
  than a margined book). Passing the gate and choosing not to trade is itself a
  discipline.

The boundary of accessible alpha runs precisely through *"real but uncapturable."*
That's a more useful map than a flat zero: it tells the next researcher where to
*stop*.

---

## What I'm actually claiming (and what I'm not)

I take limitations as seriously as results, because pretending otherwise is the
exact dishonesty the gate exists to prevent. The defensible claim is narrow: **no
edge survived *and cleared deployment* in the daily-frequency, liquid,
single-underlying-heavy, free-data slice I was able to test.** It is *not* "markets
are efficient."

The honest caveats, stated plainly: a null result's real exposure is statistical
*power*, not false discovery — and I own where the campaign is under-powered.
Despite holding ~1B rows of minute data, I closed *zero* intraday-execution tests,
so nothing here extends to sub-daily horizons — and the efficient-markets prior
makes that untested corner the *most* plausible place an edge could still hide. The
free price data purges delisted names, so the kills hold for the surviving liquid
subsample, not the small-cap tail. And the whole thing is a convenience sample that
never once tries to *capture* the bid/ask spread (market-making), only to pay it.

I'd rather hand you that list than have a reviewer find it.

---

## What this was really a demonstration of

Not a strategy. A way of working:

- **Pre-registration and falsification discipline** as a default, not an
  afterthought.
- **Friction and look-ahead realism** — the two places almost every retail backtest
  quietly cheats.
- **Provenance-first debugging** — the two most seductive numbers in the whole
  project (the Sharpe 11 and the −319% tail) were caught by asking where the data
  came from, not by any statistical test.
- **Adversarial verification** — a second pass whose only job is to attack the first
  pass's conclusions.
- **Intellectual honesty about a null** — including a full threats-to-validity
  section that argues *against* my own headline.

The infrastructure under it is real too: a collect-then-cancel data pipeline that
turns one month of a low-tier subscription into a permanent local dataset, a
survivorship-aware crypto archive that retains delisted symbols, a parity-anchored
implied-volatility engine, and ~1,800 tests pinning the whole thing.

I went looking for an edge and didn't find one. Almost nobody does. What I built
instead — a machine for telling the difference between a real edge and a mirage,
and the judgment to trust it over my own hope — is the thing the work was actually
worth.

---

*Code, the full ~9,000-word paper, every pre-registration and decision record, and
the test suite are in the repository. The data itself (licensed vendor feeds) is
not redistributed; the collection pipelines are. This is informational research,
not investment advice.*
