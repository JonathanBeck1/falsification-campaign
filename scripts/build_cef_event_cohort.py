#!/usr/bin/env python
"""Build the CEF activist + termination event cohort from free EDGAR (Phase 5 / T21).

Runs LIVE against EDGAR full-text search (``efts.sec.gov``, free, no key) to detect:

  * **activist entries** — earliest SC 13D per (known-CEF-activist, target fund),
    across Saba / Karpus / Bulldog / City of London / Ancora / Relative Value;
  * **termination events** — N-8F (deregistration), 25/25-NSE (delisting),
    N-14/425/DEFM14A (merger), DEF 14A "plan of liquidation" (announcement-time).

Writes:
  * ``output/cef/cef_event_cohort.parquet`` — one row per event (the pre-
    registration cohort for the eventual matched-control NAV study).
  * ``output/cef/cef_activist_campaigns.parquet`` — deduped campaign starts.
  * ``research/cef_event_cohort_summary.md`` — REAL counts by type/filer,
    ticker-resolution rate, vs brain/32 expectations, data walls.

EFTS is date-chunked (its deep-pagination 500s) and retried (it 500s under load),
so the build degrades on a flaky window rather than crashing. Throttled for
SEC fair-access. A full window (2015-2026) with terminations takes a while
(termination forms are high-volume market-wide); ``--no-terminations`` runs just
the activist side fast, and ``--activist-only-filers`` narrows the filer set.

Usage:
    .venv/bin/python scripts/build_cef_event_cohort.py
    .venv/bin/python scripts/build_cef_event_cohort.py --no-terminations
    .venv/bin/python scripts/build_cef_event_cohort.py --since 2015-01-01 --until 2026-06-15
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import structlog

from trader.catalysts.cef_events import (
    ACTIVIST_FILERS,
    EVENT_ACTIVIST_ENTRY,
    TERMINATION_EVENT_TYPES,
    build_cef_event_cohort,
    cohort_to_dataframe,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
OUT_COHORT = REPO / "output" / "cef" / "cef_event_cohort.parquet"
OUT_CAMPAIGNS = REPO / "output" / "cef" / "cef_activist_campaigns.parquet"
OUT_SUMMARY = REPO / "research" / "cef_event_cohort_summary.md"

DEFAULT_IDENTITY = os.environ.get(
    "SEC_EDGAR_IDENTITY", "trader-research you@example.com"
)

# brain/32 order-of-magnitude expectations (memo, 2026-06-12).
MEMO_ACTIVIST = "~150-250"
MEMO_TERMINATION = "~250"


def _campaigns_to_dataframe(campaigns):
    import pandas as pd

    rows = [
        {
            "filer_slug": c.filer_slug,
            "filer_cik": c.filer_cik,
            "target_cik": c.cik,
            "target_ticker": c.ticker or None,
            "target_name": c.name,
            "filing_date": c.filing_date.isoformat(),
        }
        for c in campaigns
    ]
    cols = ["filer_slug", "filer_cik", "target_cik", "target_ticker", "target_name", "filing_date"]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values(["filing_date", "filer_slug", "target_cik"]).reset_index(drop=True)
    return df


def write_summary(result, cohort_df, since: date, until: date, with_terminations: bool) -> None:
    n_cohort = len(cohort_df)
    n_campaigns = len(result.campaigns)
    n_terminations = len(result.terminations)

    # Ticker-resolution rate across the cohort.
    if n_cohort:
        n_ticker = int(cohort_df["target_ticker"].notna().sum())
        tick_rate = n_ticker / n_cohort * 100.0
    else:
        n_ticker, tick_rate = 0, 0.0

    # Fund-name heuristic split (how many targets read like a fund vs operating co).
    n_fund = int(cohort_df["is_fund_name"].sum()) if n_cohort else 0
    fund_rate = (n_fund / n_cohort * 100.0) if n_cohort else 0.0

    per_filer_lines = [
        f"| {slug} | {n} |"
        for slug, n in sorted(result.campaigns_per_filer.items(), key=lambda kv: -kv[1])
    ]
    per_type_lines = [
        f"| {t} | {n} |"
        for t, n in sorted(result.terminations_per_type.items(), key=lambda kv: -kv[1])
    ]

    # Filer roster (so the summary is self-describing).
    filer_roster = [f"- `{f.slug}` — {f.name} (CIK {', '.join(f.ciks)})" for f in ACTIVIST_FILERS]

    term_block = (
        [
            "## Termination events by type",
            "",
            "| event_type | count |",
            "|---|---|",
            *per_type_lines,
            "",
            f"Total termination events (deduped per target x type): **{n_terminations}** "
            f"vs memo **{MEMO_TERMINATION}**.",
            "",
        ]
        if with_terminations
        else [
            "## Termination events",
            "",
            "Skipped (`--no-terminations`). Re-run without that flag to populate the",
            "termination half of the cohort.",
            "",
        ]
    )

    lines = [
        "# CEF Event Cohort — Activist + Termination (free EDGAR)",
        "",
        f"Built LIVE from EDGAR full-text search (`efts.sec.gov`), window "
        f"**{since.isoformat()} - {until.isoformat()}**. Free, no key. This is the "
        "point-in-time **pre-registration cohort** for Phase 5 / T21 (CEF resolution-",
        "selection) — the NAV backtest comes later (needs Tiingo). Every row carries an",
        "EDGAR filing date, so the cohort has no look-ahead by construction.",
        "",
        "## Headline numbers",
        "",
        f"- Total cohort rows: **{n_cohort}** "
        f"({n_campaigns} activist entries + {n_terminations} termination events).",
        f"- Activist campaigns (deduped per filer x target): **{n_campaigns}** "
        f"vs brain/32 memo **{MEMO_ACTIVIST}**.",
        f"- Termination events: **{n_terminations}** vs memo **{MEMO_TERMINATION}**.",
        f"- Ticker-resolution rate (cohort rows with a target ticker): "
        f"**{n_ticker}/{n_cohort}** ({tick_rate:.1f}%). The rest are dead funds whose "
        "tickers EDGAR has stripped — CIK is always present (never guessed).",
        f"- Fund-name heuristic: **{n_fund}/{n_cohort}** ({fund_rate:.1f}%) of target "
        "names read like a closed-end fund (vs operating company). Used to flag, never "
        "to silently drop — see caveats.",
        "",
        "## Activist campaigns by filer",
        "",
        "| filer | campaigns |",
        "|---|---|",
        *per_filer_lines,
        "",
        "### Filer roster",
        "",
        *filer_roster,
        "",
        *term_block,
        "## Comparison vs brain/32 memo",
        "",
        "| metric | memo | this build |",
        "|---|---|---|",
        f"| activist campaigns | {MEMO_ACTIVIST} | {n_campaigns} |",
        f"| termination events | {MEMO_TERMINATION} | "
        f"{n_terminations if with_terminations else 'n/a (skipped)'} |",
        "",
        "## Data walls (HONEST)",
        "",
        "- **EFTS rate limits / 500s.** The full-text search API 500s intermittently",
        "  under load and 500s deterministically past its first 100-hit page (`from=`",
        "  deep pagination is broken). Mitigation: never paginate — chunk the date range",
        "  small enough that each window's total stays <=100 — plus per-call retry with",
        "  exponential backoff. A window that exhausts retries is logged and dropped, so",
        "  the counts here are a LOWER BOUND if any `cef_events_efts_exhausted` /",
        "  `cef_events_*_overflow` warnings appear in the run log.",
        "- **Ticker resolution for dead funds.** EDGAR strips tickers from delisted",
        "  funds, so a termination event on a long-dead fund often has `target_ticker`",
        "  null. The CIK is always present; the price/NAV ticker is recoverable",
        "  downstream via the Tiingo X-symbol list (brain/32) or EFTS `display_names`",
        "  from the fund's live era. This is why the ticker-resolution rate is below 100%.",
        "- **Fund-vs-operating-company on the 13D side.** A few known CEF activists",
        "  (Ancora especially) also file 13Ds on operating companies. The `is_fund_name`",
        "  flag marks targets whose name reads like a fund; the NAV study must filter to",
        "  confirmed CEFs (cross-reference the Tiingo NMFQS universe / N-2 filers per",
        "  brain/32) before use — this cohort is the raw superset, deliberately.",
        "- **Termination forms are market-wide.** N-8F / 25-NSE / N-14 / DEFM14A are",
        "  filed by ALL funds (and 25/25-NSE by all delisting securities), not just CEFs.",
        "  This cohort keeps every match; the fund-name flag + downstream CEF-universe",
        "  join narrow it to closed-end funds. The raw termination count is therefore an",
        "  UPPER bound on CEF terminations until that join runs.",
        "",
        "## Files",
        "",
        "- `output/cef/cef_event_cohort.parquet` — one row per event "
        "(event_type, filer, target CIK/ticker/name, filing_date, form).",
        "- `output/cef/cef_activist_campaigns.parquet` — deduped campaign starts.",
        "",
        "*Generated by `scripts/build_cef_event_cohort.py`. Pure parse/dedup/classify",
        "logic is unit-tested in `tests/financial/test_cef_events.py`.*",
    ]
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--identity", default=DEFAULT_IDENTITY, help="SEC User-Agent header")
    ap.add_argument("--since", default="2015-01-01", help="window start (ISO date)")
    ap.add_argument("--until", default="2026-06-15", help="window end (ISO date)")
    ap.add_argument(
        "--no-terminations",
        action="store_true",
        help="skip the termination half (activist campaigns only — fast)",
    )
    ap.add_argument(
        "--activist-step-days",
        type=int,
        default=60,
        help="EFTS date-chunk size for activist 13D queries (60d keeps even Saba's "
        "peak quarter under the 100-hit page; widen only for quiet filers)",
    )
    ap.add_argument(
        "--termination-step-days",
        type=int,
        default=None,
        help="override EFTS date-chunk size for ALL termination forms (default: "
        "per-form sizing from verified volumes — 25-day for 25-NSE, full-year for N-14 8C)",
    )
    ap.add_argument(
        "--throttle",
        type=float,
        default=0.3,
        help="seconds between EFTS calls (SEC fair-access)",
    )
    args = ap.parse_args()

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    with_terminations = not args.no_terminations

    log.info(
        "cef_event_cohort_start",
        since=since.isoformat(),
        until=until.isoformat(),
        terminations=with_terminations,
        filers=[f.slug for f in ACTIVIST_FILERS],
    )

    result = build_cef_event_cohort(
        since,
        until,
        identity=args.identity,
        activist_step_days=args.activist_step_days,
        termination_step_days=args.termination_step_days,
        throttle=args.throttle,
        include_terminations=with_terminations,
    )

    cohort_df = cohort_to_dataframe(result.cohort)
    campaigns_df = _campaigns_to_dataframe(result.campaigns)

    OUT_COHORT.parent.mkdir(parents=True, exist_ok=True)
    cohort_df.to_parquet(OUT_COHORT, index=False)
    campaigns_df.to_parquet(OUT_CAMPAIGNS, index=False)
    write_summary(result, cohort_df, since, until, with_terminations)

    n_activist = int((cohort_df["event_type"] == EVENT_ACTIVIST_ENTRY).sum()) if len(cohort_df) else 0
    n_term = int(cohort_df["event_type"].isin(TERMINATION_EVENT_TYPES).sum()) if len(cohort_df) else 0
    print(f"Cohort rows:          {len(cohort_df)}")
    print(f"  activist entries:   {n_activist}")
    print(f"  termination events: {n_term}")
    print(f"Campaigns per filer:  {dict(sorted(result.campaigns_per_filer.items()))}")
    if with_terminations:
        print(f"Terminations by type: {dict(sorted(result.terminations_per_type.items()))}")
    if len(cohort_df):
        n_tkr = int(cohort_df["target_ticker"].notna().sum())
        print(f"Ticker-resolved:      {n_tkr}/{len(cohort_df)} ({n_tkr/len(cohort_df)*100:.1f}%)")
    print(f"\nCohort parquet     -> {OUT_COHORT}")
    print(f"Campaigns parquet  -> {OUT_CAMPAIGNS}")
    print(f"Summary            -> {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
