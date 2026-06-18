# Pitch kit — résumé, profile, and the 2-minute version

Copy-paste building blocks for putting this project in front of a hiring manager.
Tailor the emphasis: lead with **research rigor** for quant-research roles, with
**pipelines/scale/tests** for data-engineering roles, with **experimental
discipline / not-fooling-yourself** for ML roles. Numbers below are the committed
ones — keep them exact.

---

## Résumé bullets (pick 2–4)

> **Quantitative Falsification Campaign — solo research project** (Python)
> - Pre-registered and tested **40 of 51 trading-strategy families** across equity
>   options, crypto derivatives, equity-event, and seasonality data through a
>   single fixed 8-step statistical gate (friction realism, look-ahead audit,
>   out-of-sample sign stability, matched-control permutation, provenance);
>   **0 produced a deployable edge** — and each apparent edge was decomposed into a
>   named failure class.
> - Built the falsification harness as a shared, unit-tested gate module and a
>   9-class **artifact taxonomy**; caught two data-bug "edges" (a Sharpe-11 and an
>   impossible −319% tail) by **provenance auditing**, not statistics.
> - Engineered a **collect-then-cancel data pipeline** (~1B rows of 1-minute
>   options NBBO; an ~85M-row single-name EOD option lake; a survivorship-aware
>   crypto archive retaining delisted symbols) and a parity-anchored implied-vol
>   engine, pinned by **~1,800 tests**.
> - Wrote a ~9,000-word paper with a full **threats-to-validity** analysis arguing
>   against its own headline result.

---

## LinkedIn / portfolio "Projects" blurb (short)

> **Quant Falsification Campaign** — A pre-registered study of ~50 retail-accessible
> trading strategies, each run through a fixed 8-step gate designed to kill it. The
> result is a documented *negative*: no deployable edge survived, and every
> apparent one decomposed into a named artifact class (look-ahead, friction-scale
> noise, compensated risk, survivorship, decay). The deliverable is the
> falsification apparatus and the honest map of where retail alpha is *not*.
> Python · pandas/NumPy · ~1,800 tests · options/crypto/EDGAR data pipelines.
> [link to repo / paper]

---

## One paragraph (cover letter / "about this project")

> I ran a pre-registered falsification campaign across ~50 trading-strategy families
> on free and retail-accessible data, putting each through a single fixed gate built
> to falsify it — friction realism, look-ahead audits, out-of-sample sign
> stability, matched-control permutation, and provenance checks. None produced a
> deployable edge, which was the point: the project is a demonstration of research
> discipline, not a strategy. The output is a reusable falsification harness, a
> taxonomy of how apparent edges turn out to be fake (with my own real examples,
> including two that were pure data bugs), and a paper that takes its own
> limitations as seriously as its results. I think the ability to reject my own best
> ideas before risking capital on them is the most transferable skill the work
> shows.

---

## The 2-minute verbal version ("tell me about a project")

> *Setup (20s):* "I wanted to answer one question honestly — does any tradeable edge
> survive rigorous testing on the data a solo person can actually get? So I
> pre-registered about fifty strategy families and ran each through one fixed gate
> designed to kill it."
>
> *The twist (30s):* "Forty reached a verdict and none was deployable — and that's
> the interesting part. Every promising result decomposed into a specific failure:
> a look-ahead leak, a signal smaller than its trading cost, a risk premium dressed
> up as alpha, or — twice — an outright data bug. One strategy showed a Sharpe of 11;
> turned out I was trading against a price series I'd derived from the options
> themselves. A Sharpe of 11 is never an edge, it's a receipt for a bug."
>
> *The point (40s):* "A trading desk loses money on false positives, not false
> negatives — so the skill that matters isn't finding edges, it's correctly
> rejecting mirages and knowing *why* they're mirages. I built the apparatus for
> that: a shared gate whose checks default to 'fail,' an artifact taxonomy, and
> adversarial verification. The infrastructure is real too — about a billion rows of
> options data on a collect-then-cancel pipeline, a survivorship-clean crypto
> archive, ~1,800 tests."
>
> *Close (20s):* "I also wrote up the limitations honestly — where I'm under-powered,
> what I didn't test, where an edge could still hide. I'd rather hand someone that
> list than have them find it. The honest negative was a better outcome than a
> backtest I couldn't trust."

---

## Where to point people

- **Repo** → the README is the front door (60-second version + headline tally).
- **The paper** → `research/PAPER_DRAFT.md` (full), or `docs/portfolio/BLOG_POST.md`
  (skimmable narrative — the one to actually link).
- **The rigor, if they want to dig** → `src/trader/research/gate.py` (the shared
  gate), `brain/30…` (the taxonomy), `research/THREATS_TO_VALIDITY.md` (the honest
  caveats), and any `research/*_decision.md` (a worked verdict).
