# SPAC Trust-Arbitrage — Edge Measurement (v1)

**Question.** A pre-deal SPAC holds ~$10/share of T-bills in trust; shares are
redeemable for trust + accrued interest at the deal/liquidation deadline. If you
can buy *below* trust, you lock a near-riskless yield to redemption, plus free
optionality if a deal pops the price. In 2025–2026, **is there still a discount
to capture, and does it beat T-bills enough to matter after frictions?**

Falsify-first, in the spirit of the four ideas already killed in this repo
(iron condors, VRP, IPO lock-up, CEF-activist-follow). Bottom line up front:
**no edge.** Pre-deal SPACs now trade at a small *premium* to trust, not a
discount.

Code: `src/trader/catalysts/spac_arb.py`. Tests: `tests/financial/test_spac_arb.py`.

---

## Method

1. **Sample.** EDGAR full-text search (`efts.sec.gov`) for 424B4 final
   prospectuses containing `"blank check"`, IPO years **2022–2024**. Ticker +
   CIK parsed from `display_names` (`parse_display_name`; first symbol is the
   common share class, others are R=rights / U=unit / W=warrant).
   → **339 unique SPAC CIKs**, 303 with a published common ticker.

2. **Live prices.** yfinance latest close per ticker (`fetch_live_price`).
   → **201 of 303 tickers still return data**; 102 are purged (delisted /
   liquidated → `YFPricesMissingError`).

3. **Isolate genuine pre-deal SPACs.** The 201 "live" tickers are heavily
   contaminated: many are *post-deal* operating companies that **reused the
   SPAC's ticker** after a merger — e.g. RDDT (Reddit
   ≈$171), BIRK (Birkenstock ≈$44), CART (Instacart ≈$42), DJT, CRDO ≈$222 —
   plus busted penny de-SPACs trading <$1. A pre-deal SPAC trades in a tight
   band around trust, so we keep only **price ∈ [$9.0, $13.5]**
   (`is_predeal_band`). → **55 pre-deal-plausible names.**

4. **Discount to trust.** `discount_pct = (trust − price)/price` (positive =
   below trust = favourable entry). Annualized with
   `(trust/price)^(12/months) − 1` over an assumed **9-month** horizon to
   redemption (`annualized_yield`).

5. **Trust value — assumed, then verified.** Default assumption
   **$10.60/share** (`DEFAULT_TRUST_PER_SHARE`): a SPAC IPOs at $10.00 into a
   T-bill trust; at ~5% short rates, ~1–2 years of accrued interest lifts trust
   to roughly **$10.5–$11.0**, so $10.60 is the low-middle of that band. We then
   **verified** it against the latest 10-Q XBRL (`fetch_trust_per_share`:
   `us-gaap:AssetsHeldInTrust` ÷ redeemable shares) for every band name where
   extraction succeeds.

---

## Trust-value verification (10-Q XBRL)

Per-share trust resolved cleanly for **24 of 55** band names (full-trust,
pre-deal). The assumed $10.60 is *slightly conservative*: real median is
**$10.76**.

| ticker | price | 10-Q trust/sh | discount% |
|---|---|---|---|
| LEGT | 10.00 | 10.976 | **+9.76** |
| CLBR | 10.26 | 10.559 | +2.91 |
| ALCY | 11.70 | 12.145 | +3.80 |
| DRDB | 10.54 | 10.558 | +0.17 |
| CCIX | 10.81 | 10.792 | −0.17 |
| MACI | 10.83 | 10.807 | −0.21 |
| SBXD | 10.79 | 10.761 | −0.27 |
| OACC | 10.65 | 10.595 | −0.52 |
| FACT | 10.66 | 10.591 | −0.65 |
| … (24 clean names) | | | |
| ANSC | 11.37 | 10.763 | −5.34 |

(The handful of large "discounts" — FORL, BKHA, GDST, BYNO, SPKL showing trust
of only $2.5–$7.5 — are **partial-redemption SPACs** whose XBRL mixes
pre/post-redemption figures: most of the trust was already returned, so the
residual share is *not* a real $8 discount. They are excluded as artifacts; the
$1–$25 sanity guard in `fetch_trust_per_share` catches the worst cases.)

---

## Measured distribution

**Clean full-trust pre-deal cohort (10-Q-anchored, n = 24):**

| stat | discount to trust | annualized yield |
|---|---|---|
| median | **−0.44%** | **−0.58%** |
| mean | −0.41% | −0.53% |
| p25 / p75 | −1.23% / −0.17% | — |
| min / max | −5.34% / +9.76% | — |
| at *true* discount (price < trust) | **4 of 24** | — |

**Whole band with the assumed $10.60 (n = 55):** median discount **−2.12%**,
mean −3.4%; only **8 of 55** below trust. (More negative than the clean cohort
only because $10.60 understates true trust for older names — i.e. using the
*conservative* assumption makes the premium look bigger, not smaller.)

Either way the sign is unambiguous: **the median pre-deal SPAC trades at a
premium to trust.** The negative-yield names aren't a loss you'd take — you just
hold to redemption and collect trust — but there is **no discount to harvest**,
and you'd be paying up to ~5% *over* trust for deal optionality.

### Where's the yield vs. T-bills?
- T-bills over this window ≈ **4–5%/yr**.
- A pre-deal SPAC held to redemption earns the trust's own T-bill yield
  **minus the premium you paid**. At a median premium of ~0.4–2%, your net is
  **below the T-bill rate** — you're financing someone else's optionality.
- Only **~4 of 24** names sit below trust at all, and the largest genuine
  discount (LEGT, +9.76%) is one name — not a diversifiable, repeatable strategy.

---

## What this CANNOT measure (be honest)

1. **Survivorship — the big one.** yfinance purges delisted tickers, so the
   **102/303 SPACs that already redeemed or liquidated are invisible.** Those
   are precisely the names that *realized* the trust payout. We can measure
   *currently available* discount, **not realized return**. Direction of the
   bias: the realized-return story is probably *better* than the live snapshot
   (liquidations paid trust + interest, ~the T-bill rate), but it was available
   to everyone, requires holding to a hard deadline, and the *entry discount*
   that made it interesting has since been competed away — which is exactly what
   the live premium shows.

2. **Trust value is a point estimate.** 10-Q XBRL is a quarter stale and the
   partial-redemption artifacts above show the extraction is imperfect; assumed
   $10.60 is a justified-but-flat proxy for the unresolved names.

3. **Frictions not modelled.** Pre-deal SPACs are thin: wide bid/ask on $10
   stock, hard borrow, and redemption mechanics (record dates, proration,
   minimum-cash conditions) all eat the last few bps. At a starting *premium*,
   frictions only deepen the hole.

4. **9-month horizon is assumed**, not parsed from each charter's deadline.
   Annualization is illustrative; it does not change the sign.

---

## Verdict

**Not a positive-EV niche for a small trader today.** The 2021-era free arb —
buy a SPAC at $9.70, redeem at $10.00+ — has been **competed away**. As of June
2026 the clean pre-deal cohort trades at a **median ~0.4–0.6% *premium* to
trust** (real 10-Q trust ≈ $10.76), with only ~1 in 6 names below trust at all.

- **Yield over T-bills: negative on the median name (~−0.5%/yr); marginally
  positive only on a handful of sub-trust outliers that don't form a strategy.**
- The trust floor makes it *low-risk*, but low-risk-and-no-edge is just an
  expensive money-market fund.
- Consistent with the repo's pattern: a clean, cheap **KILL**. The one residual
  worth a glance is the rare deep-discount name near a hard liquidation
  deadline (a special-situations, not systematic, play) — and even that is
  capacity-constrained and friction-bound.

**Recommendation: shelve.** Re-test only if a future SPAC supply glut pushes the
pre-deal band back to a persistent ≥2–3% sub-trust discount; the tooling here
(`fetch_spac_listings` → `build_quote` → `summarize_discounts`) will measure it
in one pass.
