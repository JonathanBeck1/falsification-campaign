# REPRODUCE.md — Quickstart & reproduction guide

This guide gets a third party from a fresh clone to (a) a green test suite, (b) a
regenerated campaign scoreboard, and (c) one representative study run end-to-end.

It also flags exactly which steps **cannot** run without the licensed options
data lake, which is **not** shipped with this repo (see "Data layout" below).

---

## 1. Environment setup

**Python.** `pyproject.toml` requires `>=3.11`. The full research path needs
**Python 3.12+** — the ThetaData client (`thetadata>=1.0.5`) is gated behind a
`python_version >= '3.12'` marker, and the reference `.venv` in this repo is
**3.12.13**. Use 3.12 to avoid surprises.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
```

**Install.** Dependencies are split into extras. For everything in this guide
(tests + studies), install the `dev` and `trading` extras:

```bash
python -m pip install -e ".[dev,trading]"
```

- `dev` → ruff, pytest, pytest-asyncio, mypy, pip-audit (needed to run the suite).
- `trading` → pandas/numpy, yfinance, quantstats, duckdb, alpaca-py, etc. (needed
  by the catalyst studies). `duckdb` + `thetadata` power the Parquet "data lake"
  read path.

> Note: one dependency (`scrapling`) installs from a pinned git commit, so the
> first install needs network and a working `git`.

**Secrets.** Most catalyst studies and the whole test suite need **no keys**.
For the trading CLI / live adapters, copy the template and fill in what you need:

```bash
cp .env.example .env   # then edit
```

`.env` and the lake are git-ignored. Never commit them.

---

## 2. Run the test suite (~1,813 financial tests)

The financial tests are fully self-contained: external services (Alpaca,
yfinance, SEC EDGAR, ThetaData, LLMs) are **mocked**, `conftest.py` isolates each
test into a clean tmp dir with all `TRADER_*/ALPACA_*/...` env vars stripped, and
there are **no** `integration`-marked tests in `tests/financial` (the
`integration` marker is defined in `pyproject.toml` and skipped by default).

```bash
# The full test suite (~1,800 tests; all external services mocked, runs offline):
pytest -q

# Or scope it to the research/financial suite explicitly (same set):
pytest tests/financial -q
```

`pyproject.toml` already wires `pythonpath = ["src"]` and
`addopts = "-m 'not integration'"`, so no `PYTHONPATH=` prefix is needed when you
invoke `pytest` from the repo root. Collection takes <1s; the suite runs offline.

> The repo README also shows `PYTHONPATH=src python -m unittest discover -s tests`,
> but **pytest is the supported runner** for the financial tests — use it.

---

## 3. Regenerate the campaign scoreboard from the registry

The campaign's source of truth is `brain/34_master_test_registry.md` (one bullet
per strategy test, with a status emoji + `**T##**` id + verdict blurb). The
scoreboard is **derived** from it and should never be hand-edited.

```bash
# Print the tally only (no file written):
python scripts/build_campaign_scoreboard.py --check

# Print the full scoreboard to stdout:
python scripts/build_campaign_scoreboard.py --stdout

# Write research/CAMPAIGN_SCOREBOARD.md (the paper's main results table):
python scripts/build_campaign_scoreboard.py
```

Expected `--check` output at time of writing (51 tests in the registry):

```
total=51  tested=40  kills=27  no-edge=8  marginal=3  data-wall=2  in-flight=2  planned=8  merged=1
```

This step needs **only the markdown registry** — no data, no keys, no network.
It is the fastest way to confirm your checkout is intact. There is unit coverage
for the parser at `tests/financial/test_campaign_scoreboard.py`.

---

## 4. Data layout (and what is NOT shipped)

The studies fall into two data classes:

### a) Free-data studies (no licensed data, no API key)

These pull split/dividend-adjusted daily bars from **yfinance** at run time via
`trader.catalysts.prices.fetch_daily`. They need **network** but no credentials.
Examples: turn-of-month, day-of-week, sell-in-May, FOMC drift, index
rebalance/reconstitution, PEAD, buyback drift, merger arb, spinoff drift, 13F
clone, insider clusters, CEF survival, and the crypto studies.

Some of these have a **pre-fetched price cache** checked into `data/` as `.pkl`
(e.g. `data/dow_spy.pkl`, `data/fomc_spy.pkl`, `data/index_rebalance_prices.pkl`,
`data/spinoff_drift_prices.pkl`), which lets the corresponding study run without
re-downloading. The wider `data/` directory is git-ignored, so treat anything
there as local/regenerable.

### b) Licensed-lake studies (REQUIRE the non-shipped options lake)

The single-name **option vol-surface** studies — index dispersion (T22),
earnings IV crush (T23), vol skew (T24), term-structure (T25), put-call-parity /
hard-to-borrow (T26) — read an **EOD option-chain Parquet lake** through
`trader.catalysts.vol_surface_data.load_option_quotes`.

That loader hard-codes the lake location:

```
$TRADER_EOD_LAKE_ROOT/
    root=TICKER/trade_year=YYYY/TICKER_YYYY-MM-DD.parquet
```

(~28 roots, 2022–2026, columns: `trade_date, root, expiration, strike, right,
bid, ask, close, volume, open_interest, underlying_close, source`).

**This lake is licensed ThetaData and is NOT included in this repository.** It is
git-ignored and lives outside the checked-out tree. See `docs/data-sharing.md`
for how the lake is exported to Parquet (`scripts/export_parquet_lake.py`),
delivered (rsync / R2 / S3), and queried (`trader.storage.parquet_lake.ParquetLake`).

> ⚠️ **Flag for third parties:** any of the scripts below **cannot run** without
> obtaining the lake yourself (a ThetaData subscription + a backfill) and then
> pointing `LAKE_ROOT` in `src/trader/catalysts/vol_surface_data.py` at your copy:
> `run_index_dispersion_study.py`, `run_earnings_iv_crush_study.py`,
> `run_vol_skew_study.py`, `run_vol_term_structure_study.py`,
> `run_putcall_parity_borrow_study.py`, `diag_putcall_dividend.py`.
> They will exit with "no priceable periods" / empty frames against an absent lake.
>
> The **unit tests** for these modules (`test_vol_surface_data.py`,
> `test_parquet_lake*.py`, `test_options_cli.py`) use synthetic fixtures and pass
> **without** the lake — only the live study *runs* need it.

---

## 5. Run one representative study end-to-end

Pick a **free-data** study so a third party can reproduce a full pre-registration
→ gate → verdict run with no licensed data and no keys. **Turn-of-month (T48)** is
a clean choice: it fetches SPY (and `^GSPC` as a cross-check) from yfinance,
computes the in-sample/out-of-sample split, runs a 1,000-trial placebo, applies
the gate, and writes its artifacts.

```bash
# Network needed (free yfinance pull); no API key.
python scripts/run_turn_of_month_study.py
```

What it writes:
- `data/turn_of_month_results.txt` — the raw run (TOM vs ROM means, Welch t,
  IS/OOS, placebo, gate PASS/FAIL).
- `output/catalysts/turn_of_month_study.json` — machine-readable summary.
- `research/turn_of_month_decision.md` — the decision doc path.

The pure stats live in `trader.catalysts.turn_of_month` and are unit-tested at
`tests/financial/test_turn_of_month.py`, so you can validate the math offline
even if the yfinance pull is rate-limited.

If you *do* have the lake, the canonical **licensed** study is index dispersion
(T22), which supports a fast smoke mode:

```bash
# Requires the options lake (section 4b). --quick = 6 names + QQQ, 8 rebalances.
python scripts/run_index_dispersion_study.py --quick
```

It prints the full brain/30 gate (mechanism, primary vega-neutral book, OOS sign
stability, key controls, sign-flip placebo, too-good tripwire) and writes
`data/index_dispersion_results.txt` + `.csv`. Without the lake it raises
`SystemExit("no priceable periods")`.

---

## 6. One-glance sanity sequence

```bash
python3.12 -m venv .venv && . .venv/bin/activate
python -m pip install -U pip && python -m pip install -e ".[dev,trading]"
pytest tests/financial -q                              # ~1,813 tests, offline
python scripts/build_campaign_scoreboard.py --check    # registry tally, offline
python scripts/run_turn_of_month_study.py              # representative study (needs network)
```

Steps 1–2 are fully offline and prove the checkout. Step 3 needs only free
network access. Anything touching the **option vol-surface** studies additionally
needs the licensed lake described in section 4b / `docs/data-sharing.md`.

## Lake configuration (env vars)

The option lakes are **not shipped** (licensed; see [DATA.md](DATA.md)). The code
resolves their location from env vars (or a git-ignored `.env`), defaulting to
repo-relative `lake/` subdirs:

```bash
export TRADER_EOD_LAKE_ROOT=/abs/path/to/lake/option_eod_quotes   # single-name EOD (T22-T26)
export TRADER_LAKE_ROOT=/abs/path/to/lake/option_quote_bars_1m     # 1-min QQQ (intraday)
```

The ~1,800 financial unit tests inject synthetic frames and need **no** lake; only
the end-to-end `scripts/run_*_study.py` options runners require it.
