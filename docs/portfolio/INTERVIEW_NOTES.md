# Interview notes — defending a negative result

The single risk with this project is that a careless listener hears "found no edge"
and files it as "the project failed." Your job in every conversation is to flip
that, fast, into "tested rigorously enough to *know*, and can name why each mirage
was a mirage." Below: the reframe, the hard questions, and crisp answers.

---

## The one-sentence reframe (memorize this)

> "A trading desk loses money on false positives, not false negatives — so the skill
> the job actually needs is rejecting mirages and knowing *why* they're fake. This
> project is forty worked examples of exactly that."

If you only land one idea, land that one. It converts a "failure" into the precise
competency the role screens for.

---

## Hard questions, and how to answer them

**"So… it didn't work? You didn't find anything?"**
> "Right — and that's the finding, not a failure. The goal was to test honestly, not
> to manufacture an edge. Finding none across forty pre-registered tests, and being
> able to name the specific reason each apparent edge was fake, is the demonstration
> of judgment. Anyone can show you a good backtest; the hard part is knowing which
> ones to throw away before you trade them."

**"Why should I care about a negative result?"**
> "Because in this domain the base rate of a 'positive' is ~100% — every retail
> backtest looks good, because the easy mistakes (look-ahead, ignoring costs,
> overfitting) all bias toward false positives. A *credible* negative is rarer and
> more informative than another pretty equity curve. It also maps the boundary:
> three effects were real but uncapturable, which tells you exactly where to stop."

**"How do you know you didn't just miss a real edge?" (the power question — the best one)**
> "That's the right question, and I address it head-on in the threats-to-validity
> section. For a null, the dominant risk is Type-II error — being under-powered — not
> false discovery. I argue two things: where the campaign is well-powered (the
> event studies with N in the thousands, where |t|≥2 detects effects of a few bps),
> 'no edge' provably means 'no edge large enough to matter'; and where it's
> under-powered (a couple of N≈50 tests), the kill rests on the after-cost loss
> being decisively *negative* in sign, which under-power can't fake. I also state
> plainly where I have no power at all — I never closed an intraday test despite
> owning the minute data — so I don't claim anything about sub-daily horizons."

**"Couldn't you just have run more tests until one passed?"**
> "That's exactly the trap I built the design to prevent. Everything was
> pre-registered — hypothesis, windows, sample size, kill criteria committed to git
> before I saw a result — so there's no specification search. And the multiple-
> comparisons point actually cuts in my favor: with forty tests you'd *expect* a
> couple of false positives by chance, and I got zero deployable survivors.
> Multiplicity can only manufacture false positives, so it can't produce a
> zero-survivor conclusion."

**"What was the hardest / most interesting bug?"**
> "Two data bugs that masqueraded as alpha. One strategy posted a Sharpe of 11 —
> which is never real — and the cause was that I was trading against a 'spot' price
> I'd reverse-engineered from the options via put-call parity, so the strategy was
> trading against its own assumption. The other reported a −319% loss, which is
> impossible for a cash position, and traced to a stock-split scale mismatch in the
> data. Both were caught by provenance — asking 'where did this number come from?' —
> not by any statistical test. That's why provenance is a gate step, not an
> afterthought."

**"Walk me through the gate / your methodology."**
> Have this cold (it's eight steps; know them in order and what each catches):
> pre-registration → friction realism (after-cost is the only ranking metric) →
> look-ahead audit → out-of-sample sign stability → pooled baseline → matched-control
> permutation → too-good tripwire → data provenance. Then the key design choice: the
> acknowledgement flags *default to false*, so a forgetful caller fails the gate
> rather than silently passing — omission becomes conspicuous instead of silent.

**"Give me one verdict end to end."**
> Pick the funding-carry decomposition (it's the cleanest story): "+31.6%/yr gross
> funding looks incredible. But it's a risk premium — retail crowds long and pays the
> short; under a delta-neutral book the short price leg gives back −25.7%/yr because
> the crowd is directionally right often enough, fees eat the rest, net −2.6%/yr. The
> gate's job is to separate 'real economic mechanism' from 'alpha,' and this is
> compensated risk, not alpha." It shows you can reason about *why*, not just compute.

**"What would you do with a real budget / on a desk?"**
> "Three things the campaign points at directly: test the intraday corner I never
> closed — I have the minute data and the prior is weakest at sub-daily horizons; get
> a delisted-retaining equity panel (CRSP/Tiingo) to test the small-cap tail the free
> data purges; and flip from *paying* the spread to *capturing* it — every test I ran
> pays friction, none provides liquidity. Those are where I'd look, with the explicit
> prior that the accessible space is mostly efficient."

**"This is a lot for one person — is it really yours?"**
> Be ready to whiteboard one piece live: the put-call-parity spot derivation, the
> matched-control permutation logic, or the variance-decomposition behind implied
> correlation. Owning the *why* of one mechanism cold settles this instantly.

---

## Tone notes

- **Lead with the reframe, not the result.** Never let "no edge" sit in the air
  unframed.
- **Be specific, fast.** Numbers and named mechanisms (the Sharpe 11, the +9.26%→
  +0.14% matched control, the 365%-of-edge friction) read as "I actually did this,"
  where vague claims read as "I read about this."
- **Volunteer a limitation before you're asked.** It's disarming and it's the exact
  trait the role wants — it signals you'll flag the risk in a live strategy too.
- **Don't oversell.** The project's credibility *is* its restraint. Claiming it
  proves markets are efficient would undo everything; "no edge in the slice I could
  test, and here's where I might be wrong" is the line that lands.
