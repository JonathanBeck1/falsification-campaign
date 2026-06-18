# Decision: CEF discount pilot — mechanism + data confirmed, capturability UNTESTED

Date: 2026-06-13
Status: Phase 5 free groundwork complete. Go/no-go on the paid full study is
Jonathan's call. This doc is the honest input.
Artifacts: `research/cef_discount_pilot.md`, `output/cef/cef_discount_pilot.json`,
`src/trader/catalysts/cef_discount.py` (11 tests).

## What the free 20-fund pilot tested (and what it could not)

Pilot = 10 live + 10 delisted CEFs, daily price vs NMFQS NAV symbol, discount =
price/NAV − 1, glitch guard on. It could test two things, and did:

1. **Data quality: PASS.** 18/20 funds usable, 1 glitch day flagged across all,
   0 funds with NAV missing. The NMFQS NAV mechanism works; the glitch guard
   fires on the +224%-class artifact. The data plan is sound.
2. **Mechanism exists: CONFIRMED (but already known).** Live CEFs show the
   expected structural discount (median −5.0%; 3 of 10 at a premium — GUT +61%,
   PTY +18%, PDI +8%). Of 8 dead funds with both windows, 7 narrowed toward 0;
   aggregate discount −5.0% (−250..−60d) → −2.9% (final 20d).

## Why this is NOT a green light (read this part twice)

The narrowing was NEVER the question. Decisions 2026-06-08 (activist-follow
+1.44% dies to frictions) and 2026-06-09 (broad tilt +0.7–3.6%/yr,
capacity-limited) already established the mechanism is real. The pilot
re-confirmed a known fact. The bar the prior CEF attempts DIED on —
capturability — is untouched here, for three reasons:

1. **No control group.** The −5.0%→−2.9% narrowing has no matched comparison.
   If discounted CEFs that did NOT resolve also tightened over the same window
   (a risk-on regime), the "capture" is beta, not resolution. This is the exact
   decision-36 sector-beta artifact. The pilot cannot distinguish them.
2. **Survivorship-conditioned selection.** The pilot used funds KNOWN to have
   resolved, hand-picked. Real-time, you don't know which discounted fund
   resolves; most stay discounted for years. The edge requires the
   activist/termination SIGNAL to predict resolution ex ante — untested.
3. **Magnitude is small and partly trivial.** Aggregate capture is ~2.1pp, and
   several "narrowed" funds (JHA, BHL, KMM, KST) started at only −1 to −3%
   discount — near-zero to begin with. The meaningful narrowing is ~3 funds
   (MZF −7.7→−1.1, GCH, ISL). One fund (NBD) WIDENED (−5.1→−7.9). Over ~a year,
   on resolvers only, before illiquid-CEF frictions, this is consistent with
   the prior "real but uncapturable" verdict — a third time.

## Data risk the pilot quantified

2 of 10 dead funds (20%) were lost to the identity-collision hazard: a delisted
fund's price ticker reused by a different security (MSP), or no price series
(EMI). This concentrates in exactly the population the study needs (resolvers).
The full study must resolve dead-fund identity via point-in-time CIK/figi, not
current ticker — brain/32's dominant risk, now measured.

## The actual decision

The full study (cost: ~1 month Tiingo Power ~$10–30 + ~2 weeks) buys a
DECISIVE capturability verdict via matched controls + the real selection
signal. It does NOT buy a likely edge. The base rate is two CEF kills; the
single most probable outcome is the matched-control study showing real-but-
uncapturable a third time, which would close the campaign.

Recommendation: proceed ONLY if the goal is the definitive answer on the
project's last lead (a worthy Outcome-B closer), not because an edge is likely.
If Jonathan would not trade a +2pp-gross, selection-dependent, capacity-limited
CEF strategy even if it passed, skip the purchase and close on the pilot —
mechanism real, capture unproven, consistent with prior CEF kills.
