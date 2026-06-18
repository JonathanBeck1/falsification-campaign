# Pre-Registration: Cash-Merger Arbitrage Spread (T40)

> Status: pre-registered design, written **before** computing any spread returns.
> The hypothesis, sample, windows, split, gate, and kill criteria are fixed here
> so a favorable specification cannot be selected after the fact. Standard
> campaign template (`brain/34_master_test_registry.md`; universal gate in
> `brain/30_campaign_findings.md`).

## 1. Hypothesis (one sentence, directional, falsifiable)

After a **cash** acquisition is announced, the target trades at a discount to the
deal price (the *arb spread*); buying the target on/after announcement and
holding to deal close captures that spread, and the **annualized after-cost
return of this strategy across ALL announced deals (completed AND broken)
exceeds the contemporaneous T-bill rate** by a margin with |t| >= 2.

## 2. Mechanism — why would this be inefficient?

The spread is the market's price for **deal-break risk** plus the time value of
capital tied up to close. The arb (Mitchell-Pulvino 2001) is compensation for
bearing a fat left tail: when a deal breaks, the target craters back toward (or
below) its undisturbed pre-bid price. The merger-arb desk is the
specialist/risk-bearing counterparty; the forced sellers are long-only holders
who sell into the pop to lock the bird-in-hand. The friction stopping full
arbitrage is precisely the break tail — you cannot diversify away regulatory /
financing / shareholder-vote risk cheaply, so a premium can persist.

**Honest prior: null / marginal.** Merger arb is a crowded, well-known strategy;
academic estimates of the *gross* annualized spread are ~4–10%/yr, but
Mitchell-Pulvino show much of it is eaten by (a) the break tail, (b)
transaction costs / market impact on the deal-break days, and (c) the fact that
the spread is widest on the riskiest (most break-prone) deals. After T-bills +
costs the surviving alpha in the literature is small and regime-dependent. Prior
is that this dies like the other 19 campaign tests.

## 3. Data + provenance

- **Instrument(s) / universe (fixed):** a **curated, hand-verified list of
  announced cash mergers with US-listed targets, 2015-01-01 .. 2025-06-30**,
  hardcoded in `src/trader/catalysts/merger_arb.py` as `MERGER_EVENTS` BEFORE any
  return is computed. Each row: target ticker, announce date, cash deal price
  per share, and outcome (`completed` / `broken`). Deals are selected to span
  both outcomes deliberately — broken deals are INCLUDED by construction, not
  filtered out (that inclusion is the whole point of the test; see §9). The list
  is assembled from public record (deal announcements anchored to EDGAR 8-K /
  DEFM14A / SC TO filings) and is fixed/committed here.
- **Source:** **SEC EDGAR full-text search** (`efts.sec.gov`) to confirm/anchor
  the announce-date filing for each target; **yfinance** for daily adjusted
  closes. Free data only (EDGAR + yfinance), per campaign scope. EDGAR requests
  carry a descriptive `User-Agent`.
- **Construction & staleness:** yfinance auto-adjusted daily closes (correct for
  return math). **KNOWN HAZARD, pre-registered:** yfinance *purges delisted
  tickers*. A **completed** cash merger delists the target, so its post-close (and
  often its entire) price history disappears from yfinance. A **broken** deal
  leaves the target trading, so it survives. This creates an **inverse
  survivorship trap**: the free price source preferentially retains exactly the
  deals that did NOT pay out the spread. This pre-registration therefore makes
  **price availability, stratified by outcome, a measured quantity** (§5/§7), and
  defines a data-wall kill (§8) if the completed-deal arm cannot be priced.
- **Event/date list:** announce date and deal price are knowable ex-ante (public
  on the announcement). Outcome (completed/broken) is NOT known at entry — it is
  used only to *label* each event for stratified reporting and to assign the
  realized terminal payoff; it never enters the entry decision. No post-hoc
  selection of which deals to include based on their return.
- **Sample span:** IS = announce year <= 2019; OOS = announce year >= 2020.

## 4. Cohort & control definition

- **Cohort (treated):** every deal in `MERGER_EVENTS` that has a usable entry
  price (first yfinance close on/after announce date) AND a usable terminal value
  (defined in §5).
- **Control / baseline:** the **contemporaneous risk-free rate** (annualized
  T-bill, pre-registered flat **4.0%/yr** as the campaign-era short rate;
  reported both gross-of and net-of T-bills). The arb must beat cash to matter.
  Secondary control: a **placebo** that assigns each event a *random* announce
  date drawn from the same ticker's trading history (no real deal) — the placebo
  spread must be ~0.
- **Signal / return per event:** annualized total return from entry to terminal,
  `(terminal / entry) ** (365 / holding_days) - 1`, minus round-trip cost.
- **t0:** first yfinance trading day on/after the announce date (entry the day
  the deal is public; conservative — no look-ahead into the pop, we pay the
  post-announcement price).

## 5. Measurement window + LOOK-AHEAD statement

- **Entry:** close on t0 (first session on/after announce date).
- **Terminal value (event time):**
  - `completed`: the **cash deal price per share** (the redemption), realized at
    the recorded/observed close date.
  - `broken`: the target's **yfinance close ~30 trading days after the break**
    (the crater), OR if the break date is not separately recorded, the realized
    yfinance path is used to mark the loss. Broken deals must be carried at their
    realized depressed price, not assumed to pay the deal price.
  - PRIMARY metric: **pooled annualized after-cost return across completed AND
    broken**, vs T-bills.
- **Look-ahead audit:** entry uses only information public at t0 (deal announced,
  deal price stated). The outcome label is applied only to compute the terminal
  payoff and to *stratify reporting*; it is NOT used to choose entries. The
  curated list is fixed before any return is computed.

## 6. Friction model

- **Round-trip cost:** single-name ~**20 bps** round trip (10 bps each way;
  merger-arb targets are less liquid than mega-caps and trade with wider spreads
  near deal events — conservative vs the 10 bps used for mega-caps in T43). On a
  broken-deal exit the realized slippage is worse; 20 bps is a floor.
- **Application:** subtract once per round trip from the gross per-deal return
  before annualizing-comparison; after-cost expectancy is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N >= 30** usable deals (with BOTH a priceable entry and a terminal).
- [ ] **Completed-deal arm priceable:** at least 15 of the *completed* deals must
      have a usable yfinance entry price. (If the free source has purged the
      completed deals, the spread cannot be measured honestly — DATA_WALL, §8.)
- [ ] **After-cost annualized return > T-bill (4%/yr)** on the pooled
      (completed+broken) sample with **|t| >= 2.0**.
- [ ] **OOS sign stability** — IS and OOS annualized-excess means same sign, both
      N >= 10.
- [ ] **Outcome stratification honest** — broken deals included; reported
      completed-only vs pooled so the break drag is visible.
- [ ] **Placebo** — random-date pseudo-deals on the same tickers show ~0 excess
      (|t| < 2).
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-5 contributor inspection.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL / DATA_WALL criteria

- **DATA_WALL** if fewer than 15 *completed* deals have a usable yfinance entry
  price — i.e. the free price source has purged the population that captures the
  spread, so the pooled (completed+broken) return cannot be measured without
  catastrophic inverse-survivorship bias. This is an honest infrastructure
  outcome (like T39), not an edge claim. The census (purge rate by outcome) is
  the evidence and is reported.
- **KILL** if, given priceable data, ANY holds:
  - After-cost pooled annualized return <= T-bill OR |t| < 2.
  - N < 30 usable deals.
  - OOS sign flip.
  - Placebo absorbs the effect (|t| < 2 net) / fewer than 5 deals drive it.
  - Completed-only looks great but pooled (incl. broken) <= T-bills — i.e. the
    "edge" is survivorship of the winners.

## 9. Limitations

The curated list is not the full merger universe — it is a fixed, hand-verified
sample. A DATA_WALL here does NOT prove merger arb has no edge; it proves the
spread cannot be measured on free (EDGAR + yfinance) data because completed-deal
targets delist and are purged. A paid delisted-retaining price source (Tiingo,
CRSP) would be required to test the hypothesis properly. The inclusion of broken
deals is the honest control; their RETAINED presence in yfinance (vs the purged
completed deals) is itself the finding.
