# Data Provenance

This repository contains the **code and methodology** of a research campaign that tested (and overwhelmingly killed) candidate trading edges. It does **not** redistribute any vendor's raw licensed dataset. Most inputs are fetched at runtime from free, public, or owned sources; a small number of **derived, transformative result artifacts** (aggregate study outputs and a catalog of public filing codes) are committed under `output/`. No file in this repository relicenses or republishes a paid data vendor's content.

This document lists every data source the campaign used. For each source: **what it is**, its **license / terms**, whether the data is **INCLUDED or EXCLUDED** from the repo (and why), and **how a third party would obtain or recreate it** to reproduce the work.

Grounding references in this repo: `src/trader/catalysts/vol_surface_data.py` (option-lake provenance), `src/trader/catalysts/crypto_data.py` (Binance archive), `src/trader/catalysts/tiingo.py` (CEF NAV/price), `src/trader/catalysts/cef_events.py` and `src/trader/catalog/build.py` (EDGAR + news), `src/trader/catalysts/prices.py` (yfinance), `brain/03_data_sources.md`, `brain/32_cef_phase5_data_plan.md`, `brain/33_data_acquisition_strategy.md`, and the decision docs in `brain/decisions/`.

## Repository data policy (the short version)

- The entire local `data/` working directory is **gitignored** (`.gitignore` ends with `data/`) — none of the `*_results.txt`, `*.pkl`, or `*.csv` scratch files there are committed.
- The 4.9 GB ThetaData **option lake** lives **outside the repo** at `$TRADER_EOD_LAKE_ROOT/` and is never committed or redistributed.
- Any **Tiingo-derived** price/NAV series are **not redistributed**; only the survivorship *universe* artifacts (symbol lists / CIK joins) derived from Tiingo's public `supported_tickers.csv` and from SEC EDGAR are committed.
- A few **derived result artifacts** under `output/catalysts/` and `output/cef/` *are* committed. These are aggregate statistics, public-domain SEC filing codes, and Claude-generated summaries — **not** raw vendor data. Details per-source below.

---

## 1. ThetaData single-name option lake (EOD option chains)

- **What it is.** A free, owned parquet "lake" of single-name end-of-day option chains collected from **ThetaData**. Layout: `lake/option_eod_quotes/root=TICKER/trade_year=YYYY/TICKER_YYYY-MM-DD.parquet`. Columns: `trade_date, root, expiration, strike, right (C/P), bid, ask, close, volume, open_interest, underlying_close, source`. Roughly **28 roots, 2022–2026**. It is the input to the entire single-name vol-surface track (dispersion T22, earnings IV crush T23, skew T24, term structure T25, hard-to-borrow T26) via the loader in `src/trader/catalysts/vol_surface_data.py`. (Provenance is documented in that module's docstring under "Data provenance (brain/30 gate, taxonomy class 4)".)
- **License / terms.** ThetaData is a **paid subscription** market-data vendor; the historical option chains are licensed to the subscriber under ThetaData's terms of service. Redistribution of the raw quote data is **not permitted** by those terms.
- **INCLUDED / EXCLUDED.** **EXCLUDED.** The lake (~4.9 GB) is stored outside the repository and is never committed. The repo references it only by an absolute path constant (`LAKE_ROOT`) and reads it at runtime. No option-quote rows are redistributed.
- **How to obtain / recreate.** (1) Subscribe to **ThetaData** (https://www.thetadata.net/) at a tier that includes historical option EOD/quotes. (2) Re-run the repository's collection scripts (the EOD option collector referenced in the recent commit history) against your own ThetaData credentials, pointed at `THETADATA_CREDENTIALS_FILE` (see `.env.example`). (3) The lake schema and per-day shard layout above let you rebuild a byte-compatible lake, after which `load_option_quotes(...)` works unchanged. Note the documented data caveat: `underlying_close` is NULL across the lake as collected, so the loader derives spot from the option chain itself via put-call parity (not from yfinance, which is split-adjusted and on the wrong scale) — any reconstruction inherits this and should rely on the parity-spot path.

## 2. Tiingo — CEF NAV and price series (closed-end-fund study)

- **What it is.** **Tiingo** EOD daily prices and, critically, the **Nasdaq MFQS NAV symbols** (`X<ticker>X`) for closed-end funds — *including delisted/dead funds with history retained*, which is the survivorship-correction set the CEF study requires. Used by `src/trader/catalysts/tiingo.py` and the Phase-5 CEF universe build (`brain/32_cef_phase5_data_plan.md`). Tiingo's public `supported_tickers.csv` is the free anchor that yields the ~620-fund / 243-delisted universe.
- **License / terms.** Tiingo is a **subscription** data provider. The free tier permits limited personal/evaluation use; full NAV/price backfill needs a paid "Power" month. The API key is read from `TIINGO_API_KEY` at call time and is **never hardcoded** (see the `tiingo.py` docstring). Tiingo's terms do **not** permit redistribution of its price/NAV data.
- **INCLUDED / EXCLUDED.** **Tiingo-derived price/NAV series are EXCLUDED — not redistributed.** What *is* committed (`output/cef/cef_tiingo_symbols.parquet`, `cef_universe.parquet`, `cef_event_cohort*.parquet`) are **universe/identity artifacts**: symbol lists, listing spans, delisted flags, and SEC-CIK joins. These encode *which funds exist and when* (membership facts derived in part from Tiingo's public free `supported_tickers.csv` plus public SEC data) — they contain **no Tiingo NAV or price values**. The daily NAV/price series themselves are never committed.
- **How to obtain / recreate.** (1) Get a free Tiingo account for the public `supported_tickers.csv` (enough to rebuild the survivorship universe). (2) For the daily NAV/price backfill, subscribe to Tiingo Power (~$10–30 for one month per the data plan) and set `TIINGO_API_KEY`. (3) Re-run the CEF universe and price/NAV fetch paths (`cef_universe.py --source tiingo`, the `tiingo.py` client). The committed universe parquet lets a third party reproduce *cohort construction* immediately; only the NAV backfill needs the key.

## 3. Binance / `data.binance.vision` — crypto perp & spot history

- **What it is.** Binance's **public, no-auth historical data archive** (an S3 bucket at `https://data.binance.vision`), read by `src/trader/catalysts/crypto_data.py`, `crossexch_funding.py`, and `crypto_vrp_data.py`. Provides USDⓈ-M perpetual **funding rates** and **klines** (`data/futures/um/monthly/...`) and **spot klines** (`data/spot/monthly/...`). Its decisive property: it is **append-only and never purges delisted symbols**, so it is survivorship-honest (dead tokens like SRMUSDT, BTSUSDT, USTUSDT retain their full history; the last available month *is* the delisting signal). Used for the crypto funding-carry, cross-exchange funding, momentum, VRP, and stablecoin-depeg studies (`brain/33`, several `brain/decisions/2026-06-14-*` kills). The cross-exchange study additionally reads **OKX** public funding-rate history.
- **License / terms.** **Free, public, no API key.** Subject to Binance's site terms of use for the public data archive. Geoblock note: the *live* host `fapi.binance.com` returns HTTP 451 in some regions, but the `data.binance.vision` archive is reachable where the live host is not — so this introduces no key/secret dependency.
- **INCLUDED / EXCLUDED.** **EXCLUDED** as raw data (downloaded at runtime; the `data/` scratch dir holding any pulled CSVs is gitignored). Aggregate **study result** text files were produced under `data/*_results.txt` but those are gitignored too. The crypto sources are *free*, so exclusion here is purely to keep the repo lean, not a licensing constraint.
- **How to obtain / recreate.** No account needed. Re-run the crypto study scripts (`scripts/run_crypto_funding_carry_study.py`, `run_crossexch_funding_study.py`, `run_crypto_momentum_study.py`, `run_crypto_vrp_study.py`, `run_stablecoin_depeg_study.py`); they pull the monthly zips directly from `data.binance.vision` (and OKX's public funding endpoint) and rebuild the universe — including delisted symbols — from scratch.

## 4. SEC EDGAR — filings, full-text search, company identity

- **What it is.** U.S. SEC **EDGAR**: company filings, the full-text search service (`efts.sec.gov`), `company_tickers.json`, and N-2/N-CEN/N-8F/SC 13D form data. Used across `src/trader/catalysts/cef_events.py` (CEF activist + termination event detection), `cef_universe.py`/`cef_resolution.py` (identity spine), `buyback_drift.py`, `merger_arb.py`, `spinoff_drift.py`, `ipo_*`, `spac_arb.py`, and the news catalog's 8-K fetch (`src/trader/catalog/build.py`). Provides the point-in-time event cohorts (every filing carries an EDGAR filing date → no look-ahead).
- **License / terms.** **Public domain / free.** U.S. government works carry no copyright. SEC requires a descriptive **User-Agent** identifying the requester (set via `TRADER_SEC_USER_AGENT`, e.g. `"trader your-email@example.com"`, per `.env.example`) and enforces fair-access rate limits. No key.
- **INCLUDED / EXCLUDED.** Raw filings are **EXCLUDED** (fetched at runtime). **Derived, public-domain artifacts ARE included:** `output/catalysts/thirteenf_filings.csv`, `thirteenf_clone_events.csv`, `output/cef/cef_event_cohort*.parquet` — these are filing-metadata cohorts (CIK, form type, filing date, accession). Because EDGAR is public domain, committing these poses no redistribution issue; they are kept so the event cohorts are reproducible without re-crawling.
- **How to obtain / recreate.** No account. Set `TRADER_SEC_USER_AGENT` to your own identifying string and re-run the relevant catalyst modules / scripts; they hit `efts.sec.gov` and `data.sec.gov` directly and rebuild the cohorts.

## 5. yfinance — Yahoo Finance daily prices (split/dividend-adjusted)

- **What it is.** Daily adjusted closes and volume via the **yfinance** library (Yahoo Finance), wrapped by `src/trader/catalysts/prices.py::fetch_daily` and used as a best-effort price source across most equity catalyst studies (spinoff drift, sell-in-may, index reconstitution/rebalance, earnings premium, day-of-week, merger arb, etc.). **Caveat documented in code:** yfinance returns *split-adjusted* closes; it is explicitly **demoted to last-resort** in the option-lake path (`vol_surface_data.py`) because adjusted closes do not match the lake's unadjusted strike scale.
- **License / terms.** yfinance is an MIT-licensed open-source library, but it scrapes **Yahoo Finance**, whose data is provided under Yahoo's terms for **personal, non-commercial** use and **without redistribution rights**. Treat the *data* as not redistributable even though the *library* is open source. No key.
- **INCLUDED / EXCLUDED.** **EXCLUDED.** No Yahoo price series are committed; data is fetched at runtime and any cached pickles live in the gitignored `data/` dir.
- **How to obtain / recreate.** `pip install yfinance` (declared in `pyproject.toml`'s `trading` extra) and re-run the studies; `prices.fetch_daily(ticker, start, end)` returns the adjusted-close/volume series. No account.

## 6. News catalog — Alpaca (Benzinga-powered) headlines + Claude classification

- **What it is.** A catalog of large single-day moves (`|daily_return| ≥ 4%`) and their likely catalysts, built by `src/trader/catalog/build.py`. Pipeline: detect big-move (ticker, date) pairs → fetch on/near-date **8-K** filings from EDGAR → fetch t-2…t+2 **headlines from Alpaca's news API** (`data.alpaca.markets/v1beta1/news`, which is **Benzinga-powered**) → have **Claude (Sonnet)** read the context and emit a structured catalog row. Output: `output/catalysts/news_catalog.parquet` (~1,978 rows) plus `news_catalog_claude.parquet` and `news_catalog_clean.parquet`.
- **License / terms.** Two upstream feeds: **Alpaca market-data / news** (requires `ALPACA_PAPER_KEY_ID` / secret; the news content is **Benzinga**-licensed and Benzinga/Alpaca terms do **not** permit redistribution of raw headline text) and the **Anthropic Claude API** (requires `ANTHROPIC_API_KEY`; usage governed by Anthropic's terms — the model *output* is the user's, but is a derived work over the inputs). EDGAR 8-K data in the pipeline is public domain.
- **INCLUDED / EXCLUDED — important nuance.** The catalog parquet files **are committed**, but they are a **derived, transformative artifact, not a redistribution of Benzinga/Alpaca content.** Audit of the columns confirms: the committed rows contain aggregate move statistics (`daily_return`, `spy_excess`, …), **public-domain SEC 8-K item codes** in `evidence_snippet` (e.g. `"8-K items=['2.02','9.01']"`, `"Date of report ..."`), a Claude-generated `category`/`subcategory`/`confidence`, and a Claude-written `brief_explanation` (e.g. *"TSLA significantly outperformed SPY, but no filing or news identifies a specific catalyst."*). **No raw Benzinga/Alpaca headline strings are stored.** The committed file is therefore safe to ship; it is the model's classification *about* public events, plus public filing codes. If a future version were to store raw vendor headline text, that column would need to be dropped before release.
- **How to obtain / recreate.** (1) Get an **Alpaca** account (paper keys are free at https://alpaca.markets/) and set `ALPACA_PAPER_KEY_ID` / `ALPACA_PAPER_SECRET_KEY`. (2) Get an **Anthropic** API key and set `ANTHROPIC_API_KEY`. (3) Set `TRADER_SEC_USER_AGENT` for the EDGAR leg. (4) Run `scripts/run_news_catalog.py` (resumable — already-cataloged events are skipped). This regenerates the catalog over the default ticker set / date window in `catalog/build.py`.

## 7. Other / minor sources

- **FRED** (Federal Reserve Economic Data) — free with an API key (`FRED_API_KEY`); used for macro series where referenced. Public/free; not redistributed (fetched at runtime). Recreate: free key at https://fred.stlouisfed.org/docs/api/api_key.html.
- **Finnhub** — free-tier API (`FINNHUB_API_KEY`) referenced in config for supplementary data; not redistributed. Recreate: free key at https://finnhub.io/.
- **Alpaca market data (bars)** — beyond the news leg, Alpaca bars/quotes are used for some execution/market-snapshot paths; same key, same non-redistribution terms; fetched at runtime.
- **Deribit DVOL / OKX** — referenced for crypto-options/cross-exchange comparisons; free public endpoints, not redistributed.

---

## Summary table

| Source | Type / terms | In repo? | Why |
|---|---|---|---|
| ThetaData option lake | Paid, no-redistribution | **No** (lives outside repo, gitignored path) | Licensed vendor data; ~4.9 GB |
| Tiingo CEF NAV/price | Paid (free tier limited), no-redistribution | **No raw data**; only derived universe/identity parquet | Licensed; NAV/price never shipped |
| Binance `data.binance.vision` / OKX | Free, public, no key | **No** (runtime fetch; scratch gitignored) | Free — excluded only for repo size |
| SEC EDGAR | Public domain, free | **Derived cohorts yes**; raw filings no | Public domain — safe to commit |
| yfinance / Yahoo | Library MIT; data personal-use, no-redistribution | **No** | Yahoo data not redistributable |
| News catalog (Alpaca/Benzinga + Claude) | Paid feeds; output is derived | **Yes — derived artifact only** | No raw headlines; SEC codes + Claude analysis |
| FRED / Finnhub / Deribit | Free (key for some) | **No** | Free; runtime fetch |

## One-line clarifier to add to the README / LICENSE notes

> This repository's MIT license covers the **code only**. It grants **no rights** over any third-party data. No licensed vendor dataset (ThetaData option quotes, Tiingo NAV/price, Alpaca/Benzinga news, Yahoo Finance prices) is redistributed here — see `DATA.md`. Committed `output/` artifacts are derived, transformative results (aggregate statistics, public-domain SEC filing codes, and model-generated classifications), not vendor raw data. To reproduce the studies, obtain the sources yourself per `DATA.md` and set the keys in `.env` (template: `.env.example`).
