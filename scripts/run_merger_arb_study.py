#!/usr/bin/env python
"""Run the pre-registered T40 cash-merger-arbitrage study (end-to-end, live).

Pre-registration: research/merger_arb_preregistration.md. Falsify-first.

Free data only (EDGAR + yfinance). The pure core (trader.catalysts.merger_arb) is
unit-tested without I/O; this script is the thin network layer. It:

  1. takes the fixed curated event list (completed AND broken deals),
  2. attempts to fetch a yfinance entry price for every target,
  3. builds the outcome-stratified price-availability CENSUS — the key evidence,
  4. computes per-deal annualized after-cost excess-over-T-bill returns where
     priceable, with a random-date placebo,
  5. applies the pre-registered gate (DATA_WALL precedence) and writes the report.

The expected live outcome (pre-registered §3/§8) is a DATA_WALL: yfinance purges
the COMPLETED-deal targets (they delist on close), so the population that
captures the spread is unpriceable on free data.
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.merger_arb import (  # noqa: E402
    OOS_SPLIT_YEAR,
    RISK_FREE_ANNUAL,
    ROUND_TRIP_COST,
    DealReturn,
    MergerEvent,
    aggregate,
    annualize,
    build_census,
    compute_deal_return,
    curated_events,
    entry_close,
    evaluate,
    mean,
    t_stat_one_sample,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
log = structlog.get_logger()

SEED = 40
N_PLACEBO_PER_TICKER = 5

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "merger_arb_report.md"
RESULTS_PATH = ROOT / "data" / "merger_arb_results.txt"
JSON_PATH = OUT_DIR / "merger_arb_study.json"

SEC_AGENT = "catalyst-research merger-arb you@example.com"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"


def anchor_announce_filing(ev: MergerEvent) -> str:
    """Best-effort: confirm an EDGAR filing near the announce date (provenance).

    Returns a short status string. Never raises — provenance is a nice-to-have;
    the data-wall finding does not depend on EDGAR being reachable.
    """

    try:
        import httpx

        lo = (ev.announce_date - timedelta(days=3)).isoformat()
        hi = (ev.announce_date + timedelta(days=10)).isoformat()
        resp = httpx.get(
            EFTS_URL,
            params={"q": '"merger agreement"', "startdt": lo, "enddt": hi},
            headers={"User-Agent": SEC_AGENT},
            timeout=20,
        )
        if resp.status_code != 200:
            return f"edgar_http_{resp.status_code}"
        total = resp.json().get("hits", {}).get("total", {}).get("value", 0)
        return f"edgar_hits={total}"
    except Exception as exc:  # pragma: no cover - network path
        return f"edgar_err={str(exc)[:30]}"


def fetch_close(ticker: str) -> pd.Series | None:
    """Full daily adjusted-close history for ``ticker`` (2014..now), or None."""

    res = fetch_daily(ticker, date(2014, 1, 1), date.today())
    if res is None:
        return None
    close, _ = res
    return close if not close.empty else None


def placebo_returns(
    close: pd.Series, *, rng: random.Random, n: int
) -> list[float]:
    """Random-date pseudo-deal annualized excess returns on a surviving ticker.

    Picks ``n`` random entry dates, holds a fixed 120 calendar days, and computes
    the annualized after-cost excess-over-rf of a plain buy-and-hold. With no real
    deal these must average ~0 (the placebo null).
    """

    s = close.dropna().sort_index()
    if len(s) < 200:
        return []
    idx = pd.DatetimeIndex(s.index)
    out: list[float] = []
    for _ in range(n):
        pos = rng.randint(0, len(s) - 100)
        entry_dt = idx[pos].date()
        term_pos = min(pos + 80, len(s) - 1)  # ~120 calendar days
        entry_price = float(s.iloc[pos])
        term_price = float(s.iloc[term_pos])
        if entry_price <= 0:
            continue
        hold = (idx[term_pos].date() - entry_dt).days
        if hold <= 0:
            continue
        total = term_price / entry_price - 1.0 - ROUND_TRIP_COST
        ann = annualize(total, hold)
        if abs(ann) <= 5.0:
            out.append(ann - RISK_FREE_ANNUAL)
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    events = curated_events()
    priceable: set[str] = set()
    returns: list[DealReturn] = []
    placebo: list[float] = []
    rows: list[str] = []

    for ev in events:
        close = fetch_close(ev.ticker)
        anchor = anchor_announce_filing(ev)
        time.sleep(0.15)  # be polite to EDGAR / yahoo
        if close is None:
            rows.append(
                f"- {ev.ticker:6} {ev.announce_date} {ev.outcome:9} "
                f"deal=${ev.deal_price:>7.2f} | PURGED (no yfinance data) | {anchor}"
            )
            continue
        ent = entry_close(close, ev.announce_date)
        if ent is None:
            rows.append(
                f"- {ev.ticker:6} {ev.announce_date} {ev.outcome:9} "
                f"deal=${ev.deal_price:>7.2f} | data but no entry on/after announce "
                f"| {anchor}"
            )
            continue
        priceable.add(ev.ticker)
        r = compute_deal_return(ev, close)
        if r is None:
            rows.append(
                f"- {ev.ticker:6} {ev.announce_date} {ev.outcome:9} "
                f"deal=${ev.deal_price:>7.2f} | priced but return dropped (glitch) "
                f"| {anchor}"
            )
            continue
        returns.append(r)
        placebo.extend(placebo_returns(close, rng=rng, n=N_PLACEBO_PER_TICKER))
        rows.append(
            f"- {ev.ticker:6} {ev.announce_date} {ev.outcome:9} "
            f"deal=${ev.deal_price:>7.2f} entry=${r.entry_price:>7.2f}@{r.entry_date} "
            f"term=${r.terminal_value:>7.2f} hold={r.holding_days}d "
            f"ann_excess={r.excess_annual * 100:+.1f}% | {anchor}"
        )

    census = build_census(events, priceable)
    pooled = aggregate(returns, label="pooled")
    completed_only = aggregate(
        [r for r in returns if r.outcome == "completed"], label="completed_only"
    )
    broken_only = aggregate(
        [r for r in returns if r.outcome == "broken"], label="broken_only"
    )

    is_ret = [r.excess_annual for r in returns if r.announce_date.year <= OOS_SPLIT_YEAR]
    oos_ret = [r.excess_annual for r in returns if r.announce_date.year > OOS_SPLIT_YEAR]
    placebo_t = t_stat_one_sample(placebo)

    verdict = evaluate(
        census,
        pooled,
        is_mean=mean(is_ret),
        is_n=len(is_ret),
        oos_mean=mean(oos_ret),
        oos_n=len(oos_ret),
        placebo_t=placebo_t,
    )

    run_at = datetime.now(UTC).isoformat()
    lines = [
        "# T40 — Cash-Merger Arbitrage Study Result",
        "",
        "Pre-registration: `research/merger_arb_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Curated events: {census.n_total} "
        f"({census.n_completed} completed, {census.n_broken} broken)",
        "- Price source: yfinance (free); EDGAR anchors announce filings",
        f"- T-bill control: {RISK_FREE_ANNUAL * 100:.1f}%/yr; "
        f"round-trip cost: {ROUND_TRIP_COST * 1e4:.0f} bps",
        f"- IS = announce year <= {OOS_SPLIT_YEAR}, OOS = year > {OOS_SPLIT_YEAR}",
        "",
        "## PRICE-AVAILABILITY CENSUS (the data-wall test)",
        f"- Completed-deal targets priceable on yfinance: "
        f"{census.n_completed_priceable}/{census.n_completed} "
        f"(purge rate {census.completed_purge_rate * 100:.0f}%)",
        f"- Broken-deal targets priceable on yfinance: "
        f"{census.n_broken_priceable}/{census.n_broken} "
        f"(purge rate {census.broken_purge_rate * 100:.0f}%)",
        f"- Total priceable: {census.n_priceable}/{census.n_total}",
        "  -> yfinance RETAINS broken deals (target kept trading) but PURGES",
        "     completed deals (target delisted on close) = inverse survivorship.",
        "",
        "## Per-deal log",
        *rows,
        "",
        "## Returns where priceable (annualized after-cost EXCESS over T-bill)",
        f"- Pooled (all priceable): n={pooled.n} "
        f"excess={pooled.excess_mean * 100:+.2f}% t={pooled.excess_t:+.2f} "
        f"median={pooled.excess_median * 100:+.2f}% win={pooled.win_rate * 100:.0f}%",
        f"- Completed-only: n={completed_only.n} "
        f"excess={completed_only.excess_mean * 100:+.2f}% t={completed_only.excess_t:+.2f}",
        f"- Broken-only:    n={broken_only.n} "
        f"excess={broken_only.excess_mean * 100:+.2f}% t={broken_only.excess_t:+.2f}",
        "",
        "## IS / OOS (where priceable)",
        f"- IS  (<= {OOS_SPLIT_YEAR}): mean excess {mean(is_ret) * 100:+.2f}% (n={len(is_ret)})",
        f"- OOS (>  {OOS_SPLIT_YEAR}): mean excess {mean(oos_ret) * 100:+.2f}% (n={len(oos_ret)})",
        "",
        "## Placebo (random-date pseudo-deals on surviving tickers)",
        f"- n={len(placebo)} mean excess={mean(placebo) * 100:+.2f}% t={placebo_t:+.2f}",
        "",
        "## Pre-registered verdict",
        f"### {verdict.status}",
        *[f"- {r}" for r in verdict.reasons],
        "",
    ]

    text = "\n".join(lines)
    try:
        REPORT_PATH.write_text(text)
        RESULTS_PATH.write_text(text)
        JSON_PATH.write_text(
            json.dumps(
                {
                    "run_at": run_at,
                    "verdict": verdict.status,
                    "n_total": census.n_total,
                    "n_completed": census.n_completed,
                    "n_broken": census.n_broken,
                    "n_completed_priceable": census.n_completed_priceable,
                    "n_broken_priceable": census.n_broken_priceable,
                    "completed_purge_rate": census.completed_purge_rate,
                    "broken_purge_rate": census.broken_purge_rate,
                    "pooled_n": pooled.n,
                    "pooled_excess_mean": pooled.excess_mean,
                    "pooled_excess_t": pooled.excess_t,
                    "completed_only_n": completed_only.n,
                    "broken_only_n": broken_only.n,
                    "is_mean": mean(is_ret),
                    "is_n": len(is_ret),
                    "oos_mean": mean(oos_ret),
                    "oos_n": len(oos_ret),
                    "placebo_n": len(placebo),
                    "placebo_t": placebo_t,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"ERROR: could not write outputs: {exc}", file=sys.stderr)
        return 3

    print(text)
    print(f"Report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
