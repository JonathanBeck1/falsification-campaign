# Decision: Following Saba's 13D into CEFs — marginal, gate failed, but not a null

Date: 2026-06-08
Status: gate FAILED, and the robustness addendum RESOLVES it: the broad
follower strategy is killed by execution frictions; the only residual value is a
convex tail that needs a resolution-selection signal we have not built.
Owner: Jonathan (via Claude Code).

## Resolution (robustness addendum, 2026-06-08)

- **Frictions kill the broad signal.** The only statistically robust effect — the
  +1m pop (+1.44% gross) — nets to **+0.44% at a realistic ~1% CEF round-trip,
  with only 48% of funds positive** (a coin flip); negative at 1.5%. CEFs trade
  with wide spreads, so the broad "follow every Saba 13D" strategy does not
  survive costs.
- **Survivorship boosts the mean, not the shape.** Even crediting all 20 resolved
  funds with a generous +15% discount capture, the all-fund +6m mean only reaches
  ~5%, while the survivor **median stays ~0**. Confirmed convex/lottery: a
  minority of big wins on resolution (liquidation/tender at NAV), most funds
  nothing.
- **Verdict:** as a broad systematic follower strategy → **killed**. The only
  viable form is a *selective convex bet* on the ~24% of campaigns that escalate
  to resolution — which needs (a) a resolution-prediction signal (which targets
  liquidate/tender vs fizzle) and (b) keyed delisted-price data (yfinance purges
  delisted tickers; stooq/CEFConnect blocked). Both are real, uncertain-payoff
  work. Do not pursue further without an explicit decision to build that selection
  signal; otherwise fall back to the SPAC-arb low-risk base.

## What we tested

Pre-registered (`research/cef_activist_study_preregistration.md`): does buying a
CEF the trading day AFTER Saba Capital's initial SC 13D is public earn excess
return vs the broad-CEF market (PCEF), or is the discount-narrowing already
priced by disclosure? NAV-free (PCEF nets out CEF-market beta). 82 Saba
campaigns from EDGAR; 62 with ≥6mo price history.

## Result: ❌ gate FAIL — but the decomposition matters

| window | mean % | median % | % pos | t | read |
|---|---|---|---|---|---|
| pre-runup [-126,-1] | −0.98 | −1.01 | 47% | −1.14 | NOT front-run (good) |
| announcement [-1,+1] | +0.23 | +0.25 | 65% | +1.78 | small pop |
| **capturable +1m** | **+1.44** | +0.84 | 65% | **+2.78** | **real, broad, significant** |
| capturable +3m | +0.96 | +0.83 | 58% | +1.49 | fades |
| capturable +6m (primary) | +2.02 | **−0.09** | 50% | +1.81 | mean up, **median ~0** |
| capturable +12m | +3.02 | **−0.18** | 48% | +1.90 | skewed/lottery |

Two distinct findings:

1. **Real short-term pop.** +1m excess is +1.44%, t=2.78, 65% positive, and the
   pre-run-up is *negative* — so it is genuinely post-disclosure, capturable, and
   broad. Statistically real.
2. **Long-term is a lottery, not a broad edge.** At 6m/12m the *mean* is positive
   but the *median* is ~0 and only ~50% of funds are positive. The positive mean
   is carried by a minority — the campaigns that resolve via tender/liquidation
   at NAV (full discount capture). The typical followed fund does nothing.

## Survivorship caveat (cuts in our favor on the mean)

20 of 82 funds were dropped as "no price" — delisted/liquidated, i.e. likely the
**biggest winners** (forced liquidation at NAV). Their absence biases the **mean
down**. Correcting it would raise the mean but make the payoff **even more
skewed/convex**, not broader. The median conclusion (typical fund: nothing) is
robust to this.

## Honest verdict

Not a kill, not a pass. Unlike the three clean nulls (condor / VRP / lock-up),
there *is* a real signal here — but it is small (a ~1.4% one-month pop) and the
longer-horizon payoff is **convex/lottery-shaped**, not a steady edge. As a
systematic *follower* strategy it does not clear the bar: the median fund offers
nothing, and CEF execution frictions (wide spreads, low liquidity) would eat much
of a 1.4% pop.

## Decision / next steps

- Do NOT declare an edge. The pre-registered gate failed (t=1.81 < 2.0).
- This is the closest thing to an edge in the whole project — worth ONE more
  rigorous pass, not a victory lap:
  1. **Survivorship-corrected v1.1**: include the 20 liquidated/delisted funds'
     final outcomes (from the de-listing 8-K / N-8F / final NAV distribution) to
     settle whether the skewed mean is real. This is the crux.
  2. **Execution-friction model**: measure the +1m pop net of realistic CEF
     bid/ask spreads and impact — does the broad short-term effect survive costs?
  3. If both hold, the shape is a **convex bet** (most flat, fat right tail on
     resolution) — fits the project's defined-risk / survivable-sizing philosophy.
- If the survivorship-corrected mean collapses or costs eat the +1m pop → kill,
  fall back to the SPAC-arb base (game 2, low-risk).

## Meta

First non-null in the project, and it appeared exactly where the thesis said to
look: a capacity-constrained niche (CEF activism) the giants can't scale into,
reached via SEC filings. Even marginal, that validates the "fish where the giants
can't" pivot over the liquid-index pond.
