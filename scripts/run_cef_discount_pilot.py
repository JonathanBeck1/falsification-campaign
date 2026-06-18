#!/usr/bin/env python
"""FREE ~20-fund CEF discount/NAV pilot — the Phase 5 go/no-go probe.

ONE question: does the CEF discount signal look ALIVE and is the Tiingo data
clean enough to trust, BEFORE any paid (Tiingo Power) purchase? This is a probe,
not the full study.

For each of ~20 hand-picked CEFs (roughly 10 LIVE + 10 DELISTED "resolution"
cases) it:
  * fetches the RAW close price (plain ticker) and RAW NAV (NMFQS ``X<ticker>X``)
    from Tiingo — both via ``tiingo.fetch_raw_close`` (free tier; <=40 symbols);
  * computes ``discount = price / nav - 1`` aligned on date (pure);
  * applies the brain/32 glitch guard (|1d price ret|>20% w/ |1d NAV ret|<2%),
    excluding flagged days from summary stats;
  * for DELISTED funds, measures whether the discount NARROWS toward 0 in the
    final ~20 trading days vs the -250..-60 day baseline (resolution capture).

Writes ``research/cef_discount_pilot.md`` + ``output/cef/cef_discount_pilot.json``.

Needs ``TIINGO_API_KEY`` (``export TIINGO_API_KEY=$(cat ~/.tiingo_key | tr -d
'[:space:]')``). With no key it still runs but every fetch returns ``None`` and
the report says so. Network-free logic is fully unit-tested in
``tests/financial/test_cef_discount.py``.

Usage:
    export TIINGO_API_KEY=$(cat ~/.tiingo_key | tr -d '[:space:]')
    .venv/bin/python scripts/run_cef_discount_pilot.py
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import structlog

from trader.catalysts.cef_discount import (
    discount_with_glitch_guard,
    resolution_narrowing,
)
from trader.catalysts.tiingo import fetch_raw_close

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
SYMBOLS_PARQUET = REPO / "output" / "cef" / "cef_tiingo_symbols.parquet"
OUT_JSON = REPO / "output" / "cef" / "cef_discount_pilot.json"
OUT_MD = REPO / "research" / "cef_discount_pilot.md"

# Fetch window: wide enough that a dead fund's full -250..-60 baseline + final-20
# window land inside it, and a live fund has years of structural-discount history.
FETCH_START = date(2015, 1, 1)
FETCH_END = date(2026, 6, 12)

# Free-tier politeness: a small gap between requests. The free hourly request
# allocation is easily tripped by bursting 40 symbols back-to-back (observed: a
# second full run in the same hour returns HTTP 429 for most symbols). This does
# NOT defeat the hourly cap — it just avoids a same-second burst; keep total runs
# per hour low.
REQUEST_DELAY_SEC = 1.0

# ~20 hand-picked price tickers. LIVE = large, well-known, still-trading CEFs
# across the discount spectrum (muni / taxable bond / equity / covered-call).
# All verified present + price_ticker_traded in cef_tiingo_symbols.parquet.
LIVE_TICKERS = [
    "GAM",  # General American Investors (equity, classic deep-discount)
    "GUT",  # Gabelli Utility Trust (famous persistent PREMIUM)
    "PEO",  # Adams Natural Resources
    "RVT",  # Royce Value Trust
    "USA",  # Liberty All-Star Equity
    "PDI",  # PIMCO Dynamic Income (often a PREMIUM name)
    "PTY",  # PIMCO Corporate & Income Opportunity (often PREMIUM)
    "BST",  # BlackRock Science & Technology
    "UTF",  # Cohen & Steers Infrastructure
    "NEA",  # Nuveen AMT-Free Quality Muni
]

# DELISTED "resolution" cases — funds that liquidated/merged, price ticker still
# resolves, history ends well before the file's as-of (clean terminal capture).
DELISTED_TICKERS = [
    "MZF",  # ended 2018-10-24
    "GCH",  # Aberdeen Greater China, ended 2018-04-27
    "ISL",  # Aberdeen Israel, ended 2018-04-27
    "JHA",  # ended 2018-12-28
    "KMM",  # ended 2018-11-19
    "KST",  # ended 2018-11-19
    "EMI",  # ended 2018-12-20
    "NBD",  # ended 2018-12-28
    "MSP",  # ended 2018-12-04
    "BHL",  # ended 2017-08-24
]


def _nmfqs(ticker: str) -> str:
    return f"X{ticker.upper()}X"


def _fetch_pair(ticker: str) -> tuple[pd.Series | None, pd.Series | None]:
    """Fetch (raw price, raw NAV) for one ticker; either may be ``None``."""

    price = fetch_raw_close(ticker, FETCH_START, FETCH_END)
    time.sleep(REQUEST_DELAY_SEC)
    nav = fetch_raw_close(_nmfqs(ticker), FETCH_START, FETCH_END)
    time.sleep(REQUEST_DELAY_SEC)
    return price, nav


def _round(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(float(x), n)


def run() -> dict:
    sym_df = pd.read_parquet(SYMBOLS_PARQUET) if SYMBOLS_PARQUET.exists() else None

    def meta(ticker: str) -> dict:
        if sym_df is None:
            return {}
        hit = sym_df[sym_df["price_ticker"].str.upper() == ticker.upper()]
        if hit.empty:
            return {}
        r = hit.iloc[0]
        return {
            "nmfqs_symbol": r["nmfqs_symbol"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
        }

    funds: list[dict] = []
    for ticker, is_delisted in (
        [(t, False) for t in LIVE_TICKERS] + [(t, True) for t in DELISTED_TICKERS]
    ):
        log.info("pilot_fetch", ticker=ticker, delisted=is_delisted)
        price, nav = _fetch_pair(ticker)
        m = meta(ticker)

        row: dict = {
            "ticker": ticker,
            "nmfqs_symbol": m.get("nmfqs_symbol", _nmfqs(ticker)),
            "delisted": is_delisted,
            "expected_end": m.get("end_date"),
            "price_days": 0 if price is None else len(price),
            "nav_days": 0 if nav is None else len(nav),
            "n_overlap": 0,
            "n_glitch": 0,
            "mean_discount": None,
            "latest_discount": None,
            "first_date": None,
            "last_date": None,
            "resolution_baseline": None,
            "resolution_final": None,
            "resolution_narrowed": None,
            "note": None,
        }

        if price is None and nav is None:
            row["note"] = "no price and no NAV"
        elif price is None:
            row["note"] = "price missing"
        elif nav is None:
            row["note"] = "NAV missing"
        else:
            res = discount_with_glitch_guard(price, nav)
            row["n_overlap"] = res.n_overlap
            row["n_glitch"] = len(res.glitch_dates)
            if not res.clean.empty:
                row["mean_discount"] = _round(res.clean.mean())
                row["latest_discount"] = _round(res.clean.iloc[-1])
                row["first_date"] = str(res.clean.index[0].date())
                row["last_date"] = str(res.clean.index[-1].date())
                if is_delisted:
                    base, fin = resolution_narrowing(res.clean)
                    row["resolution_baseline"] = _round(base)
                    row["resolution_final"] = _round(fin)
                    if base is not None and fin is not None:
                        row["resolution_narrowed"] = abs(fin) < abs(base)
            else:
                row["note"] = "no overlapping price+NAV days"

        funds.append(row)

    return _summarize(funds)


def _summarize(funds: list[dict]) -> dict:
    live = [f for f in funds if not f["delisted"]]
    dead = [f for f in funds if f["delisted"]]

    def usable(f: dict) -> bool:
        return f["n_overlap"] > 0

    live_disc = [f["mean_discount"] for f in live if f["mean_discount"] is not None]
    n_premium = sum(1 for d in live_disc if d > 0)
    live_median = (
        float(pd.Series(live_disc).median()) if live_disc else None
    )

    # Resolution-narrowing aggregate over dead funds with both windows populated.
    narrow_rows = [
        f
        for f in dead
        if f["resolution_baseline"] is not None and f["resolution_final"] is not None
    ]
    n_narrowed = sum(1 for f in narrow_rows if f["resolution_narrowed"])
    base_mean = (
        sum(f["resolution_baseline"] for f in narrow_rows) / len(narrow_rows)
        if narrow_rows
        else None
    )
    final_mean = (
        sum(f["resolution_final"] for f in narrow_rows) / len(narrow_rows)
        if narrow_rows
        else None
    )

    summary = {
        "n_funds": len(funds),
        "n_live": len(live),
        "n_delisted": len(dead),
        "n_usable": sum(1 for f in funds if usable(f)),
        "n_total_glitch_days": sum(f["n_glitch"] for f in funds),
        "n_nav_missing": sum(1 for f in funds if f["note"] in ("NAV missing", "no price and no NAV")),
        "live_mean_discount": _round(sum(live_disc) / len(live_disc)) if live_disc else None,
        "live_median_discount": _round(live_median),
        "live_n_premium": n_premium,
        "n_price_ticker_reuse": sum(
            1 for f in funds if f["note"] == "no overlapping price+NAV days"
        ),
        "n_price_missing": sum(1 for f in funds if f["note"] == "price missing"),
        "resolution_n_with_windows": len(narrow_rows),
        "resolution_n_narrowed": n_narrowed,
        "resolution_baseline_mean": _round(base_mean),
        "resolution_final_mean": _round(final_mean),
    }
    return {"summary": summary, "funds": funds}


def _fmt(x) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x * 100:+.1f}%" if abs(x) < 5 else f"{x:.2f}"
    return str(x)


def write_markdown(result: dict) -> str:
    s = result["summary"]
    funds = result["funds"]
    lines: list[str] = []
    lines.append("# CEF Discount/NAV Pilot — Phase 5 Go/No-Go Probe")
    lines.append("")
    lines.append(f"Date: {date.today().isoformat()} · FREE Tiingo tier · "
                 f"{s['n_funds']} funds ({s['n_live']} live + {s['n_delisted']} delisted)")
    lines.append("")
    lines.append("Discount = raw price close / raw NAV close - 1, aligned on date. "
                 "NAV via the NMFQS `X<ticker>X` symbol. Glitch guard (brain/32): "
                 "|1d price ret|>20% with |1d NAV ret|<2% flagged + excluded from stats.")
    lines.append("")
    if s["n_usable"] < s["n_funds"] // 2:
        lines.append("> ⚠️ **Likely a rate-limited run.** Fewer than half the funds returned "
                     "usable price+NAV — the free Tiingo hourly request cap (HTTP 429) was "
                     "probably hit. Wait for the hourly window to reset and re-run; do NOT "
                     "trust the numbers below.")
        lines.append("")

    # Per-fund table.
    lines.append("## Per-fund results")
    lines.append("")
    lines.append("| ticker | status | overlap days | mean disc | latest disc | glitch days | span |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for f in funds:
        status = "delisted" if f["delisted"] else "live"
        span = f"{f['first_date'] or '—'} → {f['last_date'] or '—'}"
        note = f" ({f['note']})" if f["note"] else ""
        lines.append(
            f"| {f['ticker']}{note} | {status} | {f['n_overlap']} | "
            f"{_fmt(f['mean_discount'])} | {_fmt(f['latest_discount'])} | "
            f"{f['n_glitch']} | {span} |"
        )
    lines.append("")

    # Live structural discount.
    lines.append("## Do live CEFs show a persistent structural discount?")
    lines.append("")
    lines.append(f"- Median discount across live funds: **{_fmt(s['live_median_discount'])}** "
                 f"(mean **{_fmt(s['live_mean_discount'])}**, skewed by premium names — use the median).")
    lines.append(f"- Funds trading at a PREMIUM (mean disc > 0): **{s['live_n_premium']}** of {s['n_live']}.")
    lines.append("")

    # Resolution narrowing — the headline.
    lines.append("## Resolution capture (THE key pilot output)")
    lines.append("")
    lines.append("For delisted/resolved funds: does the discount narrow toward 0 as the "
                 "price series ends? Baseline = mean discount in the -250..-60 trading-day "
                 "band; Final = mean over the last 20 trading days.")
    lines.append("")
    lines.append("| ticker | baseline (-250..-60) | final 20d | narrowed? |")
    lines.append("|---|---:|---:|---|")
    for f in funds:
        if not f["delisted"]:
            continue
        lines.append(
            f"| {f['ticker']} | {_fmt(f['resolution_baseline'])} | "
            f"{_fmt(f['resolution_final'])} | {_fmt(f['resolution_narrowed'])} |"
        )
    lines.append("")
    lines.append(
        f"- Dead funds with both windows populated: **{s['resolution_n_with_windows']}**; "
        f"of those, **{s['resolution_n_narrowed']}** narrowed toward 0."
    )
    lines.append(
        f"- Aggregate baseline discount **{_fmt(s['resolution_baseline_mean'])}** → "
        f"final-20d discount **{_fmt(s['resolution_final_mean'])}**."
    )
    lines.append("")

    # Data quality.
    lines.append("## Data-quality verdict")
    lines.append("")
    lines.append(f"- Funds with usable overlapping price+NAV: **{s['n_usable']}** of {s['n_funds']}.")
    lines.append(f"- Total glitch days flagged across all funds: **{s['n_total_glitch_days']}**.")
    lines.append(f"- Funds with NAV missing entirely: **{s['n_nav_missing']}**.")
    lines.append(f"- Funds with NO usable price (X-stripped ticker REUSED by a different "
                 f"security after delisting, or no price series): "
                 f"**{s['n_price_ticker_reuse'] + s['n_price_missing']}** "
                 f"(reuse={s['n_price_ticker_reuse']}, missing={s['n_price_missing']}). "
                 f"This is the identity-collision hazard flagged in brain/32 — the dominant "
                 f"data risk for the full study, concentrated in DEAD funds.")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    result = run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2))
    OUT_MD.write_text(write_markdown(result))
    s = result["summary"]
    log.info(
        "pilot_done",
        usable=s["n_usable"],
        glitch=s["n_total_glitch_days"],
        live_mean_discount=s["live_mean_discount"],
        resolution_narrowed=s["resolution_n_narrowed"],
        json=str(OUT_JSON),
        md=str(OUT_MD),
    )


if __name__ == "__main__":
    main()
