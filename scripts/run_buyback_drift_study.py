#!/usr/bin/env python
"""Run the pre-registered T41 buyback-announcement-drift study (end-to-end).

Pre-registration: research/buyback_drift_preregistration.md. Falsify-first.

Free data only:
  * SEC EDGAR full-text search (efts.sec.gov) for buyback-authorization 8-Ks
    (Item 8.01, earnings-bundled Item 2.02 excluded) — descriptive User-Agent.
  * yfinance daily adjusted closes for prices; SPY as the market benchmark.

Network-bound; the pure core lives in trader.catalysts.buyback_drift and is
unit-tested without I/O.
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.buyback_drift import (  # noqa: E402
    EVENT_WINDOWS,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    BuybackEvent,
    BuybackFiling,
    abnormal_returns,
    aggregate,
    compute_event,
    dedup_filings,
    evaluate_gate,
    mean,
    net_vs_matched,
    resolve_t0_index,
    sample_matched_cars,
    t_stat_one_sample,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
log = structlog.get_logger()

# --- Pre-registered constants (fixed BEFORE results; see pre-reg) -------------
IDENTITY = "trader-catalyst research buyback-drift you@example.com"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

# Fixed OR-union of new-authorization phrases (pre-reg §3).
PHRASES = [
    '"approved a share repurchase"',
    '"approved a stock repurchase"',
    '"authorized a share repurchase"',
    '"authorized a stock repurchase"',
    '"new share repurchase program"',
    '"new stock repurchase program"',
]
REQUIRE_ITEM = "8.01"  # Item 8.01 (Other Events) must be present
EXCLUDE_ITEMS = {"2.02"}  # exclude earnings-bundled filings (PEAD confound)

SINCE = date(2015, 1, 1)
UNTIL = date(2025, 12, 31)
OOS_SPLIT = date(2020, 1, 1)  # IS: file_date < 2020 ; OOS: >= 2020
N_MATCHED_PER_EVENT = 4  # matched (ticker, year) placebo windows per event
SEED = 41

# yfinance-unresolvable / non-equity symbols seen in EDGAR display_names that we
# never try to trade (warrants, units, indices). Kept tiny + transparent.
_BAD_TICKER = re.compile(r"[^A-Z.\-]")

SUBJ_RE = re.compile(r"\(([A-Z.\-]{1,6})\)\s+\(CIK (\d+)\)")

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "buyback_drift_report.md"
RESULTS_PATH = ROOT / "data" / "buyback_drift_results.txt"
JSON_PATH = OUT_DIR / "buyback_drift_study.json"


def _get_with_retry(
    client: httpx.Client, params: dict, *, tries: int = 6
) -> dict | None:
    """GET the EFTS endpoint with backoff on EDGAR's intermittent 5xx throttling.

    EDGAR returns sporadic 500s under load even within fair-use pacing; the
    retries make deep pagination reliable. Returns the parsed JSON, or ``None``
    after exhausting retries (logged, so a short page can be distinguished from
    a fetch failure upstream).
    """

    for attempt in range(tries):
        try:
            resp = client.get(EFTS_URL, params=params)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
        except Exception as exc:  # network blip -> back off and retry
            log.warning("edgar_attempt_failed", attempt=attempt, error=str(exc))
            time.sleep(1.5 * (attempt + 1))
    return None


def _fetch_phrase(
    client: httpx.Client, phrase: str, *, max_pages: int = 60
) -> tuple[list[BuybackFiling], int, bool]:
    """Fetch all qualifying 8-K filings for one phrase across the full span.

    Returns ``(filings, reported_total, complete)``. ``complete`` is False if a
    page could not be fetched after retries (so the caller can flag truncation
    honestly rather than silently undercounting).
    """

    out: dict[str, BuybackFiling] = {}  # accession -> filing (dedup exhibits)
    reported_total = 0
    complete = True
    for page in range(max_pages):
        params = {
            "q": phrase,
            "forms": "8-K",
            "startdt": SINCE.isoformat(),
            "enddt": UNTIL.isoformat(),
            "from": page * 100,
        }
        payload = _get_with_retry(client, params)
        if payload is None:
            log.warning("edgar_page_unfetchable", phrase=phrase, page=page)
            complete = False
            break
        hits_block = payload.get("hits", {})
        if page == 0:
            reported_total = int(hits_block.get("total", {}).get("value", 0) or 0)
        hits = hits_block.get("hits", [])
        if not hits:
            break
        for h in hits:
            s = h.get("_source", {})
            items = set(s.get("items") or [])
            if REQUIRE_ITEM not in items:
                continue
            if items & EXCLUDE_ITEMS:
                continue
            adsh = s.get("adsh")
            if not adsh or adsh in out:
                continue
            names = s.get("display_names") or []
            if not names:
                continue
            m = SUBJ_RE.search(names[0])
            if not m:
                continue
            ticker, cik = m.group(1), m.group(2)
            if _BAD_TICKER.search(ticker) or ticker == "-":
                continue
            fdate_raw = s.get("file_date")
            if not fdate_raw:
                continue
            out[adsh] = BuybackFiling(
                ticker=ticker,
                cik=cik,
                file_date=date.fromisoformat(fdate_raw),
                accession=adsh,
            )
        if len(hits) < 100:
            break
        time.sleep(0.25)  # EDGAR fair-use pacing
    return list(out.values()), reported_total, complete


def build_event_list() -> tuple[list[BuybackFiling], int, bool]:
    """Fetch + dedup the buyback-authorization filing list.

    Returns ``(deduped_filings, raw_accessions, all_complete)``.
    """

    headers = {"User-Agent": IDENTITY}
    all_filings: dict[str, BuybackFiling] = {}
    all_complete = True
    with httpx.Client(headers=headers, timeout=30.0) as client:
        for phrase in PHRASES:
            filings, total, complete = _fetch_phrase(client, phrase)
            all_complete = all_complete and complete
            log.info(
                "phrase_fetched",
                phrase=phrase,
                qualifying=len(filings),
                reported_total=total,
                complete=complete,
            )
            for f in filings:
                all_filings.setdefault(f.accession, f)
            time.sleep(0.3)
    raw = len(all_filings)
    deduped = dedup_filings(list(all_filings.values()))
    log.info("buyback_events_built", raw_accessions=raw, deduped=len(deduped))
    return deduped, raw, all_complete


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    filings, raw_accessions, edgar_complete = build_event_list()
    if not filings:
        _write_data_wall("EDGAR returned no qualifying buyback 8-Ks.")
        print("DATA_WALL: no qualifying filings", file=sys.stderr)
        return 1

    spy = fetch_daily("SPY", SINCE - timedelta(days=40), UNTIL + timedelta(days=120))
    if spy is None:
        print("ERROR: could not fetch SPY benchmark", file=sys.stderr)
        return 2
    spy_close, _ = spy

    # Group filings by ticker so we fetch each price history once.
    by_ticker: dict[str, list[BuybackFiling]] = {}
    for f in filings:
        by_ticker.setdefault(f.ticker, []).append(f)

    events: list[BuybackEvent] = []
    matched_cars: list[float] = []
    warnings: list[str] = []
    incomplete = 0
    price_misses = 0

    for ticker, t_filings in by_ticker.items():
        lo = min(f.file_date for f in t_filings) - timedelta(days=20)
        hi = max(f.file_date for f in t_filings) + timedelta(days=160)
        prices = fetch_daily(ticker, lo, hi)
        if prices is None:
            price_misses += 1
            warnings.append(f"{ticker}: price history unavailable")
            continue
        close, _ = prices
        abn = abnormal_returns(close, spy_close)
        index = pd.DatetimeIndex(abn.index)

        ticker_events: list[BuybackEvent] = []
        t0_positions: list[int] = []
        event_years: list[int] = []
        for f in t_filings:
            ev = compute_event(abn, f.file_date, ticker)
            if ev is None:
                incomplete += 1
                continue
            ticker_events.append(ev)
            t0 = resolve_t0_index(index, f.file_date)
            if t0 is not None:
                t0_positions.append(t0)
                event_years.append(ev.t0_date.year)
        if not ticker_events:
            warnings.append(f"{ticker}: no complete event windows")
            continue
        events.extend(ticker_events)

        matched_cars.extend(
            sample_matched_cars(
                abn,
                t0_positions,
                event_years,
                index,
                n_per_event=N_MATCHED_PER_EVENT,
                window=EVENT_WINDOWS[PRIMARY_WINDOW],
                rng=rng,
            )
        )
        time.sleep(0.05)

    if len(events) < 30:
        _write_data_wall(
            f"Only {len(events)} complete-window events after price join "
            f"(need >= 30). Raw accessions: {raw_accessions}."
        )
        print(f"DATA_WALL: {len(events)} usable events (< 30)", file=sys.stderr)
        # still emit the report below for the record
    # ----- aggregate (PRIMARY window) -----
    primary_cars = [e.cars[PRIMARY_WINDOW] for e in events]
    stats = aggregate(primary_cars, label="buyback")
    matched_stats = aggregate(matched_cars, label="matched", round_trip_cost=0.0)

    net, net_t = net_vs_matched(primary_cars, matched_cars)

    # IS / OOS split on event year.
    is_cars = [e.cars[PRIMARY_WINDOW] for e in events if e.t0_date.year < OOS_SPLIT.year]
    oos_cars = [e.cars[PRIMARY_WINDOW] for e in events if e.t0_date.year >= OOS_SPLIT.year]
    is_after = [c - ROUND_TRIP_COST for c in is_cars]
    oos_after = [c - ROUND_TRIP_COST for c in oos_cars]

    # 2x friction stress (robustness, non-gating).
    stress_after = [c - 2 * ROUND_TRIP_COST for c in primary_cars]

    gate = evaluate_gate(
        n_events=len(events),
        after_cost_mean=stats.after_cost_mean,
        after_cost_t=stats.t_stat,
        is_mean=mean(is_after),
        is_n=len(is_cars),
        oos_mean=mean(oos_after),
        oos_n=len(oos_cars),
        matched_mean=matched_stats.gross_mean,
        matched_t=matched_stats.t_stat,
        net_vs_matched_mean=net,
        net_vs_matched_t=net_t,
    )

    # ----- secondary windows (reported, non-gating) -----
    secondary = {}
    for name in EVENT_WINDOWS:
        if name == PRIMARY_WINDOW:
            continue
        secondary[name] = aggregate([e.cars[name] for e in events], label=name)

    # Top-5 contributor inspection (too-good tripwire hygiene).
    ranked = sorted(events, key=lambda e: e.cars[PRIMARY_WINDOW], reverse=True)
    top5 = ranked[:5]
    mean_ex_top5 = (
        mean([e.cars[PRIMARY_WINDOW] for e in ranked[5:]]) if len(ranked) > 5 else float("nan")
    )

    run_at = datetime.now(UTC).isoformat()
    warning_lines = [f"- {w}" for w in warnings[:25]] or ["- None"]
    if len(warnings) > 25:
        warning_lines.append(f"- ... and {len(warnings) - 25} more")

    lines = [
        "# T41 — Buyback-Announcement-Drift Study Result",
        "",
        "Pre-registration: `research/buyback_drift_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Span: {SINCE} .. {UNTIL}",
        f"- Source: EDGAR full-text 8-K (Item {REQUIRE_ITEM}, excl {sorted(EXCLUDE_ITEMS)})",
        f"- EDGAR pagination complete (no truncation): {edgar_complete}",
        f"- Phrases (OR): {', '.join(PHRASES)}",
        "- Benchmark: SPY; abnormal return = stock - SPY (beta=1)",
        f"- PRIMARY window: {PRIMARY_WINDOW} = {EVENT_WINDOWS[PRIMARY_WINDOW]} (t0=file+1 session)",
        f"- Round-trip cost: {ROUND_TRIP_COST * 1e4:.0f} bps/event",
        f"- IS = year < {OOS_SPLIT.year}, OOS = year >= {OOS_SPLIT.year}",
        "",
        "## Sample accounting",
        f"- Raw qualifying accessions (Item 8.01, not 2.02): {raw_accessions}",
        f"- Deduped (ticker, quarter) filings: {len(filings)}",
        f"- Distinct tickers fetched: {len(by_ticker)}",
        f"- Tickers with no price history: {price_misses}",
        f"- Complete-window events: {len(events)}",
        f"- Events dropped (incomplete/glitch window): {incomplete}",
        f"- Matched (ticker, year) placebo windows: {len(matched_cars)}",
        "",
        "## Buyback-drift CAR (PRIMARY car_p1_p21 = [+1,+21])",
        f"- N events: {stats.n}",
        f"- Gross mean abnormal return: {stats.gross_mean * 100:+.3f}%",
        f"- After-cost mean: {stats.after_cost_mean * 100:+.3f}%",
        f"- After-cost t-stat: {stats.t_stat:+.2f}",
        f"- Median: {stats.median * 100:+.3f}%",
        f"- Win rate: {stats.win_rate * 100:.1f}%",
        f"- Cross-event Sharpe (mean/std of CARs): {stats.sharpe:+.3f}",
        f"- 2x-friction-stress after-cost mean: {mean(stress_after) * 100:+.3f}% "
        f"(t={t_stat_one_sample(stress_after):+.2f})",
        "",
        "## Matched (ticker, year) non-event control (placebo)",
        f"- N windows: {matched_stats.n}",
        f"- Mean abnormal return: {matched_stats.gross_mean * 100:+.3f}%",
        f"- t-stat: {matched_stats.t_stat:+.2f}",
        "",
        "## Net of matched control (the true drift)",
        f"- Net (cohort mean - matched mean): {net * 100:+.3f}%",
        f"- Welch t: {net_t:+.2f}",
        "",
        "## IS / OOS (decay check)",
        f"- IS  (< {OOS_SPLIT.year}) after-cost mean: {mean(is_after) * 100:+.3f}% "
        f"(n={len(is_cars)}, t={t_stat_one_sample(is_after):+.2f})",
        f"- OOS (>= {OOS_SPLIT.year}) after-cost mean: {mean(oos_after) * 100:+.3f}% "
        f"(n={len(oos_cars)}, t={t_stat_one_sample(oos_after):+.2f})",
        "",
        "## Secondary windows (non-gating)",
        *[
            f"- {name}: gross {sc.gross_mean * 100:+.3f}% after-cost "
            f"{sc.after_cost_mean * 100:+.3f}% t={sc.t_stat:+.2f} (n={sc.n})"
            for name, sc in secondary.items()
        ],
        "",
        "## Too-good tripwire / top-5 contributor inspection",
        "- Top-5 event CARs: "
        + ", ".join(
            f"{e.ticker} {e.t0_date} {e.cars[PRIMARY_WINDOW] * 100:+.1f}%" for e in top5
        ),
        f"- Mean ex-top-5: {mean_ex_top5 * 100:+.3f}% (vs full {stats.gross_mean * 100:+.3f}%)",
        "",
        "## Pre-registered gate verdict",
        f"### {'PASS' if gate.passed else 'FAIL'}",
        *[f"- {r}" for r in gate.reasons],
        "",
        "## Coverage warnings",
        *warning_lines,
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
                    "edgar_complete": edgar_complete,
                    "raw_accessions": raw_accessions,
                    "n_filings_deduped": len(filings),
                    "n_events": len(events),
                    "n_matched": len(matched_cars),
                    "primary_gross_mean": stats.gross_mean,
                    "primary_after_cost_mean": stats.after_cost_mean,
                    "primary_after_cost_t": stats.t_stat,
                    "primary_win_rate": stats.win_rate,
                    "primary_sharpe": stats.sharpe,
                    "matched_mean": matched_stats.gross_mean,
                    "matched_t": matched_stats.t_stat,
                    "net_vs_matched": net,
                    "net_vs_matched_t": net_t,
                    "is_mean": mean(is_after),
                    "is_n": len(is_cars),
                    "oos_mean": mean(oos_after),
                    "oos_n": len(oos_cars),
                    "mean_ex_top5": mean_ex_top5,
                    "gate_passed": gate.passed,
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


def _write_data_wall(reason: str) -> None:
    text = (
        "# T41 — Buyback-Announcement-Drift — DATA_WALL\n\n"
        f"Run at: {datetime.now(UTC).isoformat()}\n\n"
        f"Reason: {reason}\n"
    )
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(text)
    REPORT_PATH.write_text(text)


if __name__ == "__main__":
    raise SystemExit(main())
