# Brain 32 — Phase 5 Data Plan: CEF Resolution-Selection Study

Date: 2026-06-12
Status: data plan adopted; build not started (Phase 4 has priority).
Scope: brain/29 Phase 5; constraints from decisions 2026-06-08
(cef-activist-follow-marginal) and 2026-06-09 (cef-survival-falsified);
gate checklist from brain/30.

## ⚠️ AMENDMENT 2026-06-13 — the SEC series/class identity spine is a DEAD END

The universe-spine build (`cef_universe.py`, 38 tests) ran live against SEC and
falsified this doc's core identity assumption:

- The org-type-32 series/class dataset is **~99% insurance separate accounts /
  variable-annuity entities** (2,697 of 2,719 in 2026). **0 of 27,574 org-32
  rows across 2015–2026 carry a class ticker; 0 of 458 distinct CIKs resolve to
  an exchange listing.**
- Real exchange-listed CEFs (General American GAM CIK 40417, Tortoise NDP CIK
  1547158) register as **single entities with no series/class IDs** → they are
  **entirely absent** from this file.
- brain/32's "423 CEF CIKs in 2019" reproduced EXACTLY (good URL/format
  validation) but is **materially misleading** — those 423 are separate
  accounts, not closed-end funds. Same surface-validates-but-wrong trap the
  campaign exists to catch.

**Corrected identity spine:** `company_tickers.json` + N-2 / N-CEN filers,
intersected with the Tiingo NMFQS `X…X` NAV-symbol list (which is independently
verified to retain delisted funds). The membership/listing-span/delisted-flag
machinery in `cef_universe.py` is correct and reusable — it just needs
repointing to this layer. The "~620 funds / 243 delisted" figure comes from the
Tiingo X-symbol list, NOT from the SEC series/class CSV.

### Repoint result (2026-06-13, built + tested live, free)

The corrected spine anchored on the Tiingo NMFQS list now exists
(`cef_universe.py --source tiingo`, 54 tests, `output/cef/cef_tiingo_symbols.parquet`):

- **646 distinct `X…X` CEF NAV symbols; 619 with history; 243 delisted 2015–2026
  (exact match to memo).** 597/646 (92%) strip-X to an exchange-traded price
  ticker. Per-year live counts decline 509 (2015) → 415 (2026) — net attrition,
  as expected. The survivorship-free anchor is validated.
- **Two known weaknesses (both downstream-fixable, documented in code):**
  1. CIK join resolves only 326/646 (22/243 dead funds) — SEC strips dead
     tickers. Dead funds are retained via price ticker; CIK recoverable via
     EFTS display_names (existing `resolve_ticker` path) when EDGAR event joins
     are needed.
  2. CIK join over-captures ~35 ticker collisions (XCATX→Caterpillar, etc.) —
     the NAV symbol is a real CEF, only the attached CIK is wrong. Filter
     downstream by requiring the CIK to be an N-2/N-CEN filer (CEFs file N-CEN;
     operating companies file 10-K). Columns `cik_resolved`/`price_ticker_traded`
     support this filter.

**Decision boundary reached:** the free identity groundwork is DONE. The next
step — daily NAV/price backfill for the full ~620-fund universe — requires one
month of Tiingo Power (~$10–30), a PURCHASE the maintainer must approve. Free tier supports a
~20-fund pilot first. Phase 5 pauses here pending the continue/stop call.

---

## The decisive finding (verified 2026-06-12, free, no key)

Tiingo carries the **Nasdaq MFQS NAV symbols** (`X<ticker>X`, exchange NMFQS)
for closed-end funds — **including dead funds, with history retained after
delisting**. From Tiingo's public `supported_tickers.csv`:

- 651 `X…X` NMFQS symbols; 620 with history overlapping 2015+.
- **243 delisted between 2015 and 2026** — the survivorship-correction set.
- Spot checks: XADEX back to 1999; dead funds XNDPX/XTTPX end 2025-04-30;
  XBNYX (the +224% glitch fund from decision 2026-06-09) ends 2026-02-10.
- Price side equally retained (NDP/TTP/NTG end 2024-12-20, MZF 2018-08-03).
- Strip-the-X maps 576/651 symbols to a US-listed price ticker (218/243 of
  the dead ones); ~75 names need one-time manual mapping.

This solves the two blockers from the prior CEF kills simultaneously:
per-fund daily NAV (discount = price vs NAV) AND delisted coverage.

## Universe / NAV options evaluated

| option | NAV | delisted | cost | verdict |
|---|---|---|---|---|
| **Tiingo (price + X…X NAV symbols)** | daily, incl. dead | yes (verified) | free tier (~3 months patience) or Power ~$10–30/mo for one month | **RECOMMENDED** |
| Sharadar SFP | none | yes | ~$200–400/yr | reject (no NAV) |
| EDGAR series/class CSVs + EFTS | n/a (identity layer) | ground truth | free | **REQUIRED spine** regardless of vendor |
| CEFConnect/CEFA scraping | live funds only | **purged** | ToS risk | reject — survivorship-biased by construction |
| N-PORT/N-CEN structured data | monthly, 60-day lag | yes | free | integrity cross-check only |

Identity caveats (verified): SEC series/class CSVs have Entity Org Type 32 =
closed-end (423 CEF CIKs in 2019) but NULL tickers for CEFs;
`data.sec.gov/submissions` strips tickers from dead funds; EFTS
`display_names` preserve them; N-CEN (2018+) carries exchange+ticker.

## Event signal from EDGAR (CEFs file no 8-K/10-K)

- Activist entry: SC 13D / 13D/A from known CEF activists (Saba CIK 1510281,
  Karpus, Bulldog/Special Opportunities, City of London, + Ancora, Relative
  Value Partners). 13G→13D switches count as entries.
- Termination/resolution: **N-8F** (deregistration, gold standard), 25/25-NSE
  (delisting), N-14/N-14 8C/425/DEFM14A (merger), DEF/PRE 14A containing
  "plan of liquidation" (announcement-time, tradeable), SC TO-I/TO-T (weak
  alone; existing `cef_resolution.py` corroboration logic applies).

Verified EFTS counts 2015–2026 → deduped order of magnitude: ~150–250
activist campaigns + ~250 termination events against a ~620-fund universe;
resolved-activist-target sub-cohort N≈40–60 (must be stated in the Phase 5
pre-registration).

## The pipeline (one concrete build)

Parquet tables in the existing lake layout:
1. `cef_universe` — CIK, name, org-type-32 flag per year, category, ticker,
   NAV symbol, listing start/end. Point-in-time membership.
2. `cef_prices` — daily close/adjClose incl. delisted (Tiingo).
3. `cef_nav` — daily NAV per X…X symbol incl. delisted (Tiingo NMFQS).
4. `cef_discount` — derived, with **glitch guard**: flag any day where
   |1d price return| > 20% while |1d NAV return| < 2% (catches the
   BNY-class artifact by construction).
5. `cef_events` — generalize existing `src/trader/catalysts/cef_events.py`
   from Saba-only to multi-filer + termination forms; outcome labels via
   existing `cef_resolution.py`.
6. `cef_outcomes` — terminal-value reconciliation for every dead fund
   (last traded price vs final distribution per N-8F/final N-CSR).

Study design hooks (brain/30 checklist): matched controls on
(discount decile × category × year) — feasible because NAV covers the FULL
universe; benchmark = matched-control basket, never PCEF (kills the
decision-36 sector-beta artifact); cluster/bootstrap SEs by
sponsor × resolution-quarter; CAR on discount close.

Effort: ~2 weeks elapsed. Cash cost: one month of Tiingo Power (~$10–30).

## Biggest risk to validity (named now, before any result)

The hypothesis IS the right tail, and the tail observations are exactly the
delisted funds whose terminal values are least reliable — last-traded price ≠
final liquidation distribution, and vendor adjustment glitches concentrate
there. Mandatory mitigation: the glitch guard PLUS manual N-8F/final-
distribution reconciliation of every observation in the top contribution
decile before any result is written down (brain/30 checklist item 7 made
concrete).

## Existing infrastructure that carries over (verified in repo)

- `src/trader/catalysts/cef_events.py` — EDGAR EFTS client + Saba dedup
  (needs multi-filer generalization).
- `src/trader/catalysts/cef_resolution.py` — resolution classifier,
  unit-tested, reusable as-is for outcome labels.
- `src/trader/catalysts/tiingo.py` — delisted-aware EOD client
  (TIINGO_API_KEY must be re-exported; key file at ~/.tiingo_key).
- `cef_survival_backtest.py` harness exists but carries v1 flaws (broad-ETF
  benchmark, no glitch guard) — supersede, don't extend.
