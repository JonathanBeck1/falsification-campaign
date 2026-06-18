# Strategic reassessment: where edge can and cannot be found for this shop

Date: 2026-06-08
Status: durable strategic conclusion after four rigorous falsification studies.
Owner: Jonathan (via Claude Code).

## The scoreboard

Four ideas, each tested with pre-registration, placebo/benchmark controls, an
out-of-sample split, and cost realism:

| idea | arena | result |
|---|---|---|
| Intraday iron condor (+ tunings) | liquid index (SPY/QQQ) | no edge; crushed by buy-and-hold |
| VRP-gated premium selling | liquid index | break-even; the "+$1,273 edge" was selection bias |
| IPO lock-up expiry | single-name IPOs | clean null; the classic effect has decayed/arbitraged |
| Follow Saba's 13D into CEFs | capacity-constrained niche | real but **uncapturable**: broad signal dies to frictions; residual is a convex tail needing selection |

Three clean nulls and one real-but-uncapturable convex tail.

## The pattern (this is the finding)

1. **In the liquid-index arena, there is nothing for us.** That is the most
   competed corner of finance; we should never have expected otherwise.
2. **Even in a capacity-constrained niche the giants cannot scale into (CEF
   activism), the *broad* systematic edge is absent.** What remained was a
   convex tail — a minority of campaigns that resolve at NAV pay off, most do
   nothing — and capturing it requires *selection skill* (predicting which
   resolve), not a mechanical rule.
3. **So the law we kept re-deriving holds:** anything backtestable from public
   data, and anything on a calendar, is priced. The residual is always either
   (a) a known risk premium, (b) a decayed/arbitraged anomaly, or (c) a convex
   tail that needs judgment to harvest.

## The honest conclusion about edge

A durable *systematic* edge from public data does not exist for a solo shop —
four independent rigorous tests agree, and so does the entire academic
literature (SPIVA: ~90% of *professional* managers underperform the index over
15 years). The honest options are therefore not "find a better signal." They are:

1. **Index the core + make rare, selective convex bets.** Most capital in the
   index; occasionally express a high-conviction, non-systematic view with
   defined-risk long optionality, sized to survive being wrong/early many times.
   This is judgment, not a system — and you cannot know ex-ante whether you are
   right or merely stubborn. The CEF convex tail is the one live candidate shape.
2. **Structural/capacity niches** where small size is the moat (SPAC trust arb,
   micro-cap special situations). Real, but inherently small — edge XOR scale.
   For modest capital that is acceptable; it will not be life-changing.
3. **Tooling, not alpha.** The discipline and infrastructure we built is itself
   valuable (research, risk-understanding, mistake-avoidance) even if it never
   prints money directly.

## What we actually produced, and why it has value

The negative results ARE the product. The most expensive mistake in markets is
not "failing to find an edge" — it is *thinking you found one*, sizing up, and
being destroyed (the LTCM path). This project built a machine that reliably
distinguishes a real edge from a compelling story, and used it to kill four
stories before a dollar was risked. That machine — pre-registration, placebo
controls, OOS splits, friction and survivorship realism, the falsify-first
reflex — and the reusable filings/event-study infrastructure, is the durable
asset.

## The validated instinct

Every prior the operator stated up front was confirmed by the evidence:
- "Analysis, not structure" — structures were exhaustively priced; ✓.
- "If it's a true edge and it's found, it stops working" — lock-up decayed
  exactly so; ✓.
- "Temperament over signal" — the operator predicted every null and chose to
  reassess rather than double down. That disposition, not any signal, is the
  thing that does not blow up.

## Decision

Stop hunting for a *broad systematic* edge; that question is answered (no). Spend
remaining effort on:
- **Securing a certain floor** (measure SPAC-arb — is there a real low-risk
  positive-EV base?), and
- **The one live convex candidate** (can the CEF resolution-selection signal be
  built well enough to harvest the tail?),
and otherwise default to index + rare conviction + the discipline that keeps us
out of the graveyard. Treat any future "systematic edge" claim as guilty until
it survives the same machine that killed these four.
