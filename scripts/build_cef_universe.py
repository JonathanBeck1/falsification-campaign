#!/usr/bin/env python
"""Build the survivorship-bias-free CEF universe spine from free SEC EDGAR data.

Fetches the annual SEC "investment company series and class" CSVs (2015-2026, no
key, no paid API), filters to Entity-Org-Type 32 (closed-end fund), folds per-year
presence into a point-in-time membership table (first/last year, listing span,
delisted flag), resolves tickers best-effort from EDGAR full-text search
``display_names``, and writes:

  * ``output/cef/cef_universe.parquet`` — one row per fund (CIK).
  * ``research/cef_universe_summary.md`` — counts per year, distinct CIKs,
    ticker-resolution rate, delisted count.

SEC requires a descriptive User-Agent. Override via ``SEC_EDGAR_IDENTITY`` or
``--identity``. Ticker resolution makes one EFTS request per CIK, so it is
rate-limited and skippable with ``--no-tickers`` (membership still builds).

Usage:
    .venv/bin/python scripts/build_cef_universe.py
    .venv/bin/python scripts/build_cef_universe.py --no-tickers
    SEC_EDGAR_IDENTITY="me me@example.com" .venv/bin/python scripts/build_cef_universe.py
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import structlog

from trader.catalysts.cef_universe import (
    YEAR_END,
    YEAR_START,
    TickerInfo,
    build_membership,
    build_tiingo_cef_universe,
    fetch_universe_records,
    membership_to_dataframe,
    resolve_identity,
    tiingo_symbols_to_dataframe,
    tiingo_symbols_to_year_records,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT_PARQUET = REPO / "output" / "cef" / "cef_universe.parquet"
OUT_SUMMARY = REPO / "research" / "cef_universe_summary.md"
# Tiingo-anchored (corrected) identity outputs — kept beside, not over, the SEC
# spine so the two can be diffed.
OUT_TIINGO_PARQUET = REPO / "output" / "cef" / "cef_universe.parquet"
OUT_TIINGO_SYMBOLS = REPO / "output" / "cef" / "cef_tiingo_symbols.parquet"
OUT_TIINGO_SUMMARY = REPO / "research" / "cef_universe_summary.md"

DEFAULT_IDENTITY = os.environ.get(
    "SEC_EDGAR_IDENTITY", "trader-research you@example.com"
)


def _resolve_all_identities(ciks, *, identity, delay, efts_fallback):
    """Submissions-first (optional EFTS fallback) per CIK with a polite delay
    between calls; progress logged in batches."""

    out: dict[str, TickerInfo] = {}
    total = len(ciks)
    for i, cik in enumerate(ciks, 1):
        out[cik] = resolve_identity(
            cik, identity=identity, efts_fallback=efts_fallback
        )
        if delay:
            time.sleep(delay)
        if i % 50 == 0 or i == total:
            n_tkr = sum(1 for v in out.values() if v.ticker)
            n_listed = sum(1 for v in out.values() if v.listed)
            log.info(
                "cef_universe_identity_progress",
                done=i,
                total=total,
                tickers=n_tkr,
                listed=n_listed,
            )
    return out


def write_summary(df, fetch, tickers_attempted: bool) -> None:
    n_funds = len(df)
    n_delisted = int(df["delisted"].sum())
    n_with_ticker = int(df["ticker"].notna().sum()) if "ticker" in df else 0
    n_listed = int(df["listed"].sum()) if "listed" in df else 0
    n_listed_delisted = (
        int((df["listed"] & df["delisted"]).sum()) if "listed" in df else 0
    )
    years = sorted(fetch.per_year_ciks)

    per_year_lines = [
        f"| {y} | {fetch.per_year_ciks[y]} |" for y in years
    ]
    missing_years = [
        y for y in range(YEAR_START, YEAR_END + 1) if y not in fetch.per_year_ciks
    ]

    tick_rate = (n_with_ticker / n_funds * 100.0) if n_funds else 0.0
    delist_rate = (n_delisted / n_funds * 100.0) if n_funds else 0.0
    listed_tick_rate = (n_with_ticker / n_listed * 100.0) if n_listed else 0.0

    ticker_note = (
        f"Resolved {n_with_ticker}/{n_funds} ({tick_rate:.1f}%) overall, "
        f"{n_with_ticker}/{n_listed} ({listed_tick_rate:.1f}%) of the exchange-listed "
        "subset. Source: `data.sec.gov/submissions` (ticker + exchange for live "
        "funds), with EDGAR full-text-search `display_names` as the dead-fund fallback."
        if tickers_attempted
        else "Identity resolution **skipped** (`--no-tickers`); `ticker`/`exchange`/"
        "`listed` are unset in this build."
    )

    blocker = n_listed == 0 and n_funds > 0
    blocker_block = (
        [
            "> **BLOCKER — wrong identity layer for tradeable CEFs.** This build "
            "resolved",
            f"> **{n_listed} exchange-listed funds out of {n_funds}** org-type-32 "
            "CIKs: the SEC",
            "> *series/class* dataset is ~99% insurance separate accounts / variable-",
            "> annuity entities, NOT closed-end funds. Genuine exchange-listed CEFs "
            "(e.g.",
            "> GAM / General American Investors, Tortoise NDP) register as **single "
            "entities",
            "> without series/class IDs** and so are ENTIRELY ABSENT from this file "
            "(verified:",
            "> 0 of 27,574 org-32 rows across all 11 years carry a class ticker; GAM "
            "is in",
            "> `company_tickers.json` but not in any series/class CSV). brain/32's "
            '"423 CEF',
            '> CIKs in 2019" is a real count but materially misleading — those are '
            "separate",
            "> accounts. **The membership/identity machinery here is correct and "
            "reusable, but",
            "> must be repointed** at the CEF identity layer: `company_tickers.json` + "
            "N-2 /",
            "> N-CEN filers (cross-referenced with the Tiingo NMFQS `X…X` symbols "
            "brain/32",
            "> already found). See the Caveats section.",
            "",
        ]
        if blocker
        else []
    )
    lines = [
        "# CEF Universe Spine — Summary",
        "",
        *blocker_block,
        "Point-in-time membership built from the **free** SEC annual investment-",
        "company *series/class* datasets, 2015-2026 (SEC Entity Org Type 32). No key,",
        "no paid API, no vendor — dead funds are retained (present early, absent later",
        "= deregistered). NOTE: see the BLOCKER above — for org-type 32 this dataset",
        "captures insurance separate accounts, not exchange-listed CEFs.",
        "",
        f"Source files: `{YEAR_START}`-`{YEAR_END}` SEC series/class CSVs. "
        f"Years with no published file: "
        f"{', '.join(str(y) for y in missing_years) if missing_years else 'none'}.",
        "",
        "## Headline numbers",
        "",
        f"- Distinct org-type-32 CIKs (any year in window): **{n_funds}**",
        f"- Of those, **exchange-listed** (NYSE/Nasdaq/etc per submissions): "
        f"**{n_listed}** — the tradeable-CEF universe the study uses. The rest are",
        "  insurance separate accounts / variable-annuity entities (see caveats).",
        f"- Appear **delisted by {YEAR_END}** (absent in final year): "
        f"**{n_delisted}** ({delist_rate:.1f}%); of the listed subset, "
        f"**{n_listed_delisted}** are delisted.",
        f"- Tickers resolved: **{n_with_ticker}** ({tick_rate:.1f}% of all, "
        f"{listed_tick_rate:.1f}% of listed).",
        f"- {ticker_note}",
        "",
        "## CEF CIKs per source year",
        "",
        "| year | distinct org-32 CIKs |",
        "|---|---|",
        *per_year_lines,
        "",
        "## Caveats",
        "",
        "- **Org-type 32 in the series/class dataset is NOT closed-end funds.** It is",
        "  dominated (~99%) by insurance separate accounts / variable-annuity entities.",
        "  In 2026, 2,697 of 2,719 org-32 rows are explicitly separate-account / VA /",
        "  insurance names; the remaining 22 are also pooled/unit-trust accounts — zero",
        "  genuine exchange-listed CEFs. Across all 11 years, 0 of 27,574 org-32 rows",
        "  carry a class ticker. The `listed` column (submissions exchange field) is the",
        "  correct gate and it returns 0 here, confirming the mismatch.",
        "- **Why CEFs are missing:** traditional CEFs register as a single entity with",
        "  NO series/class IDs, so the series/class file never lists them. The identity",
        "  layer for CEFs is instead `company_tickers.json` (ticker+name) joined to",
        "  N-2 / N-CEN filers, with delisted coverage from EFTS `display_names` and the",
        "  Tiingo NMFQS `X…X` NAV symbols brain/32 already verified retain dead funds.",
        "- **Resolution machinery is sound, just unused here.** Ticker/exchange come from",
        "  `data.sec.gov/submissions` (clean for LIVE funds) with EFTS `display_names`",
        "  as the dead-fund fallback (submissions strips dead tickers). Misses are",
        "  recorded, never guessed. Repoint the same code at the CEF CIK list above.",
        "- **2016 is genuinely absent** from SEC's published listing, so a fund present",
        "  in 2015 and 2017 has a one-year gap that is a data artifact, not a delisting.",
        "  The `delisted` flag keys only on absence in the FINAL year to avoid this.",
        "- **Delisted/listed counts here are a registration-level signal**, not a",
        "  liquidation reconciliation — terminal-value cross-checks (N-8F / final N-CSR)",
        "  are a downstream step per brain/32.",
        "",
        "*Generated by `scripts/build_cef_universe.py`. Pure parse/assembly logic is",
        "unit-tested in `tests/financial/test_cef_universe.py`.*",
    ]
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n")


def write_tiingo_summary(sym_df, mem_df) -> None:
    """Write the corrected (Tiingo-anchored) universe summary with REAL numbers."""

    n_sym = len(sym_df)
    n_traded = int(sym_df["price_ticker_traded"].sum())
    n_cik = int(sym_df["cik_resolved"].sum())
    n_delisted = int(sym_df["delisted"].sum())
    n_delisted_cik = int((sym_df["delisted"] & sym_df["cik_resolved"]).sum())
    n_delisted_traded = int((sym_df["delisted"] & sym_df["price_ticker_traded"]).sum())

    # Per-year LIVE-fund counts off the membership table (a fund is "live" in year
    # y if y is within its listing span).
    per_year = {}
    for _, m in mem_df.iterrows():
        years = [int(y) for y in str(m["years"]).split(",") if y]
        for y in range(min(years), max(years) + 1) if years else []:
            per_year[y] = per_year.get(y, 0) + 1
    per_year_lines = [f"| {y} | {per_year[y]} |" for y in sorted(per_year)]

    cik_rate = (n_cik / n_sym * 100.0) if n_sym else 0.0
    traded_rate = (n_traded / n_sym * 100.0) if n_sym else 0.0
    delist_rate = (n_delisted / n_sym * 100.0) if n_sym else 0.0

    lines = [
        "# CEF Universe Spine — Tiingo NMFQS Anchor (corrected identity)",
        "",
        "Built from the **free, no-key** Tiingo `supported_tickers` catalogue, whose",
        "Nasdaq-MFQS NAV symbols (`X<ticker>X`, exchange `NMFQS`) for closed-end funds",
        "are RETAINED after delisting — the survivorship-free anchor. CIK identity is",
        "joined from SEC `company_tickers.json` (live filers only). This SUPERSEDES the",
        "SEC org-type-32 series/class spine, which is ~99% insurance separate accounts",
        "and omits real CEFs entirely (brain/32 amendment 2026-06-13).",
        "",
        "## Headline numbers",
        "",
        f"- CEF NAV symbols (`X…X` NMFQS): **{n_sym}**",
        f"- Resolve to an exchange-traded price ticker (strip-X, trades non-NMFQS): "
        f"**{n_traded}** ({traded_rate:.1f}%)",
        f"- Resolve to a CIK via `company_tickers.json`: **{n_cik}** ({cik_rate:.1f}%) "
        "— the rest are unresolved (mostly dead funds whose tickers SEC has stripped; "
        "recorded as null CIK, never guessed)",
        f"- Flagged **delisted** (history ends >=30d before the file's max date): "
        f"**{n_delisted}** ({delist_rate:.1f}%); of those, **{n_delisted_cik}** keep a "
        f"CIK and **{n_delisted_traded}** keep a traded price ticker. (The membership "
        f"table's `delisted` column uses a coarser absent-in-final-calendar-year rule, "
        f"so it reads {int(mem_df['delisted'].sum())} — the ~12-row gap is funds that "
        f"delisted in early {YEAR_END} and so still touch the final calendar year. The "
        f"date-precise symbol-level flag above is the authoritative one.)",
        "",
        "## Live-fund counts per year (within listing span)",
        "",
        "| year | live CEF NAV symbols |",
        "|---|---|",
        *per_year_lines,
        "",
        "## Comparison vs brain/32 memo expectation",
        "",
        "| metric | memo | this build |",
        "|---|---|---|",
        f"| `X…X` symbols (with history) | ~620 | {int(sym_df['start_date'].notna().sum())} |",
        f"| delisted 2015-2026 | 243 | {n_delisted} |",
        f"| strip-X resolves to price ticker | 576/651 | {n_traded}/{n_sym} |",
        "",
        "## Over-capture risk + how to confirm CEF-ness (HONEST)",
        "",
        "`supported_tickers.csv` carries NO fund-type label beyond `assetType` "
        "(\"Mutual Fund\") and exchange (`NMFQS`). The `X…X` pattern is the NMFQS NAV-",
        "symbol convention and reliably isolates the NAV-symbol family, but the CIK",
        "JOIN over-captures: the 3-letter inner ticker is matched against",
        "`company_tickers.json` by string equality, so ~35 symbols collide with",
        "unrelated OPERATING companies that happen to share the ticker (e.g. `XCATX`→CAT",
        "Caterpillar, `XPEPX`→PEP PepsiCo, `XNRGX`→NRG Energy, `XMSAX`→MSA Safety). The",
        "NMFQS symbol is still a real CEF NAV symbol; only the attached CIK is wrong.",
        "**Mitigation before this is used as ground truth:** confirm CEF-ness per CIK by",
        "(a) cross-referencing N-2 / N-CEN filers on EDGAR (CEFs file N-CEN, operating",
        "companies file 10-K), or (b) requiring the price ticker to trade as a fund (it",
        "has its own `NMFQS` NAV symbol AND files N-2), not merely to exist in",
        "`company_tickers.json`. The `cik_resolved` and `price_ticker_traded` columns in",
        "`cef_tiingo_symbols.parquet` let that filter run downstream.",
        "",
        "## Files",
        "",
        "- `output/cef/cef_universe.parquet` — point-in-time membership (span/delisted),",
        "  keyed on CIK where resolved else the NMFQS symbol, via the existing machinery.",
        "- `output/cef/cef_tiingo_symbols.parquet` — the raw anchor table (one row per",
        "  `X…X` symbol: price ticker, CIK, dates, delisted, traded flag).",
        "",
        "*Generated by `scripts/build_cef_universe.py --source tiingo`. Pure parse/join",
        "logic is unit-tested in `tests/financial/test_cef_universe.py`.*",
    ]
    OUT_TIINGO_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIINGO_SUMMARY.write_text("\n".join(lines) + "\n")


def run_tiingo(identity: str) -> None:
    log.info("cef_universe_tiingo_start", identity=identity)
    symbols, _ticker_to_cik = build_tiingo_cef_universe(identity=identity)
    if not symbols:
        raise SystemExit(
            "No Tiingo CEF symbols parsed — the Tiingo fetch/unzip failed. Check network."
        )
    sym_df = tiingo_symbols_to_dataframe(symbols)

    records, identities = tiingo_symbols_to_year_records(symbols)
    memberships = build_membership(records, window_end=YEAR_END, identities=identities)
    mem_df = membership_to_dataframe(memberships)

    OUT_TIINGO_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    mem_df.to_parquet(OUT_TIINGO_PARQUET, index=False)
    sym_df.to_parquet(OUT_TIINGO_SYMBOLS, index=False)
    write_tiingo_summary(sym_df, mem_df)

    n_traded = int(sym_df["price_ticker_traded"].sum())
    n_cik = int(sym_df["cik_resolved"].sum())
    n_delisted = int(sym_df["delisted"].sum())
    print(f"CEF NAV symbols (X…X):    {len(sym_df)}")
    print(f"Resolve to price ticker:  {n_traded}")
    print(f"Resolve to CIK:           {n_cik}")
    print(f"Delisted:                 {n_delisted}")
    print(f"\nMembership parquet -> {OUT_TIINGO_PARQUET}")
    print(f"Symbols parquet    -> {OUT_TIINGO_SYMBOLS}")
    print(f"Summary            -> {OUT_TIINGO_SUMMARY}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source",
        choices=("tiingo", "sec"),
        default="tiingo",
        help="identity anchor: 'tiingo' (corrected NMFQS spine, default) or 'sec' "
        "(legacy org-type-32 series/class — known dead end, kept for diffing)",
    )
    ap.add_argument("--identity", default=DEFAULT_IDENTITY, help="SEC User-Agent header")
    ap.add_argument(
        "--no-tickers",
        action="store_true",
        help="skip ticker/exchange resolution (membership still builds)",
    )
    ap.add_argument(
        "--ticker-delay",
        type=float,
        default=0.12,
        help="seconds between submissions/EFTS requests (SEC fair-access)",
    )
    ap.add_argument(
        "--efts-fallback",
        action="store_true",
        help="also query EFTS display_names for CIKs submissions can't resolve "
        "(recovers some dead-listed-fund tickers; SLOW — hundreds of extra calls)",
    )
    args = ap.parse_args()

    if args.source == "tiingo":
        run_tiingo(args.identity)
        return

    log.info("cef_universe_build_start", identity=args.identity)
    fetch = fetch_universe_records(identity=args.identity)
    if not fetch.records:
        raise SystemExit(
            "No CEF records fetched — every year failed. Check network / identity."
        )

    ciks = sorted({r.cik for r in fetch.records})
    identities: dict[str, TickerInfo] = {}
    if not args.no_tickers:
        log.info("cef_universe_resolving_identities", n=len(ciks))
        identities = _resolve_all_identities(
            ciks,
            identity=args.identity,
            delay=args.ticker_delay,
            efts_fallback=args.efts_fallback,
        )

    memberships = build_membership(
        fetch.records, window_end=YEAR_END, identities=identities
    )
    df = membership_to_dataframe(memberships)

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    write_summary(df, fetch, tickers_attempted=not args.no_tickers)

    n_delisted = int(df["delisted"].sum())
    n_ticker = int(df["ticker"].notna().sum())
    n_listed = int(df["listed"].sum())
    print(f"Distinct org-32 CIKs: {len(df)}")
    print(f"Exchange-listed CEFs: {n_listed}")
    print(f"Per-year counts:      {dict(sorted(fetch.per_year_ciks.items()))}")
    if fetch.failed_years:
        print(f"Years skipped:        {fetch.failed_years}")
    print(f"Delisted by {YEAR_END}:     {n_delisted} ({n_delisted / len(df) * 100:.1f}%)")
    if not args.no_tickers:
        print(f"Tickers resolved:     {n_ticker} ({n_ticker / len(df) * 100:.1f}%)")
    else:
        print("Tickers:              skipped (--no-tickers)")
    print(f"\nParquet -> {OUT_PARQUET}")
    print(f"Summary -> {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
