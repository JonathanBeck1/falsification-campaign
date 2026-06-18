"""Run the pre-registered T42 spin-off post-event drift study.

Pre-registration: research/spinoff_drift_preregistration.md.

Pipeline (only this script touches the network):
  1. EDGAR full-text search for Form 10-12B filers 2015-2025 (the registration a
     spin-off uses), deduped to the earliest 10-12B per CIK. Registration-based
     => survivorship-safe (delisted/bankrupt spincos included).
  2. Map each filer to its spinco ticker from EDGAR's display_names.
  3. yfinance prices for spinco + SPY; t0 = first regular-way trading day (first
     yfinance day). Compute market-adjusted forward CARs from t0+1 (PRIMARY).
  4. Placebo: same-name later random windows + a pooled random (name, date) pool.
  5. IS (<=2019) vs OOS (>=2020) decay split, top-5 contributor drop, after-cost
     gate, and a 2x-friction stress. Honestly counts every dropped name.

Usage:
    .venv/bin/python scripts/run_spinoff_drift_study.py
    .venv/bin/python scripts/run_spinoff_drift_study.py --start 2015 --end 2025
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
import re
import time
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import structlog
import yfinance as yf

from trader.catalysts.spinoff_drift import (
    NEED_HI,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    EventMetrics,
    SpinoffEvent,
    after_cost_mean,
    aggregate,
    compute_event_metrics,
    drop_top_contributors,
    evaluate_gate,
    placebo_cars,
    split_is_oos,
)

warnings.filterwarnings("ignore")
log = structlog.get_logger("spinoff_drift.runner")

EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
USER_AGENT = (
    os.getenv("TRADER_SEC_USER_AGENT")
    or "trader-catalyst spinoff-drift-research you@example.com"
)
HEADERS = {"User-Agent": USER_AGENT}

OUT_DIR = Path(__file__).resolve().parents[1] / "data"
UNIVERSE_CACHE = OUT_DIR / "spinoff_drift_universe.csv"
PRICE_CACHE = OUT_DIR / "spinoff_drift_prices.pkl"
RESULTS_TXT = OUT_DIR / "spinoff_drift_results.txt"

PLACEBO_DRAWS_PER_NAME = 5  # same-name random non-event windows per spinco
POOLED_PLACEBO_DRAWS = 600  # pooled random (name, date) windows
MIN_PLACEBO_GAP_TD = NEED_HI + 5  # placebo windows start well after the event

_LINES: list[str] = []
_PRICE_CACHE: dict[str, pd.Series | None] = {}


def emit(line: str = "") -> None:
    print(line, flush=True)
    _LINES.append(line)


# --------------------------------------------------------------------------- #
# EDGAR universe (I/O)
# --------------------------------------------------------------------------- #
def fetch_universe(start_year: int, end_year: int) -> list[SpinoffEvent]:
    """All distinct Form 10-12B filers in [start_year, end_year], earliest per CIK.

    Survivorship-safe by construction: the 10-12B is a *registration*, filed
    before the spin completes, so the universe includes spincos that later
    delisted. Tickers are read from EDGAR's display_names (current SEC mapping).
    """

    if UNIVERSE_CACHE.exists():
        df = pd.read_csv(UNIVERSE_CACHE, dtype=str)
        log.info("universe.cache", n=len(df))
        return [
            SpinoffEvent(
                ticker=r.ticker,
                cik=r.cik,
                filing_date=date.fromisoformat(r.filing_date),
                name=r.name,
            )
            for r in df.itertuples()
            if isinstance(r.ticker, str) and r.ticker
        ]

    seen: dict[str, tuple[date, str | None, str]] = {}
    for yr in range(start_year, end_year + 1):
        frm = 0
        while True:
            try:
                r = requests.get(
                    EDGAR_FTS,
                    headers=HEADERS,
                    params={
                        "forms": "10-12B",
                        "startdt": f"{yr}-01-01",
                        "enddt": f"{yr}-12-31",
                        "from": frm,
                    },
                    timeout=30,
                )
                hits = r.json().get("hits", {}).get("hits", [])
            except Exception:
                log.warning("edgar.page_failed", year=yr, frm=frm)
                break
            if not hits:
                break
            for h in hits:
                src = h.get("_source", {})
                disp = src.get("display_names", [])
                if not disp:
                    continue
                d0 = disp[0]
                mcik = re.search(r"CIK (\d+)", d0)
                cik = mcik.group(1) if mcik else None
                if not cik:
                    continue
                mtk = re.search(r"\(([A-Z][A-Z.\-]{0,5})\)", d0)
                tk = mtk.group(1) if mtk else None
                fd = src.get("file_date", "")
                if cik not in seen or fd < seen[cik][0]:
                    seen[cik] = (fd, tk, d0)
            frm += 10
            time.sleep(0.12)
            if frm > 400:  # safety against runaway pagination
                break
        time.sleep(0.2)

    events = [
        SpinoffEvent(ticker=tk, cik=cik, filing_date=date.fromisoformat(fd), name=name)
        for cik, (fd, tk, name) in seen.items()
        if tk
    ]
    events.sort(key=lambda e: e.filing_date)
    OUT_DIR.mkdir(exist_ok=True)
    pd.DataFrame(
        [
            {
                "cik": e.cik,
                "ticker": e.ticker,
                "filing_date": e.filing_date.isoformat(),
                "name": e.name,
            }
            for e in events
        ]
    ).to_csv(UNIVERSE_CACHE, index=False)
    log.info(
        "universe.fetched", distinct_ciks=len(seen), with_ticker=len(events)
    )
    return events


def _download(ticker: str, start: date, end: date) -> pd.Series | None:
    key = f"{ticker}|{start}|{end}"
    if key in _PRICE_CACHE:
        return _PRICE_CACHE[key]
    try:
        df = yf.download(
            ticker, start=start, end=end, progress=False, auto_adjust=True
        )
    except Exception:
        _PRICE_CACHE[key] = None
        return None
    if df is None or df.empty or "Close" not in df:
        _PRICE_CACHE[key] = None
        return None
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.name = ticker
    out = s if len(s) > 0 else None
    _PRICE_CACHE[key] = out
    return out


# --------------------------------------------------------------------------- #
# report helpers
# --------------------------------------------------------------------------- #
def _report(metrics: list[EventMetrics], label: str) -> None:
    res = aggregate(metrics, label=label)
    emit(f"\n=== {label}  (N={res.n_events}) ===")
    emit(f"{'window':<14}{'mean':>10}{'median':>10}{'%pos':>8}{'t-stat':>9}")
    for name, w in res.windows.items():
        emit(
            f"{name:<14}{w.mean:>+10.4f}{w.median:>+10.4f}"
            f"{w.pct_positive:>8.2f}{w.t_stat:>+9.2f}"
        )


@dataclass
class Collected:
    metrics: list[EventMetrics]
    used: int
    no_price: int
    short: int
    glitch_or_edge: int
    same_name_placebo: list[float]


def collect(events: list[SpinoffEvent], spy: pd.Series, rng: random.Random) -> Collected:
    metrics: list[EventMetrics] = []
    placebo: list[float] = []
    used = no_price = short = glitch_or_edge = 0
    for e in events:
        # pull a wide window: from before the spin (to be safe) to ~1.5y after.
        s = _download(e.ticker, e.filing_date, date(2025, 6, 30))
        if s is None or len(s) < NEED_HI + 5:
            no_price += 1
            continue
        s = s.dropna().sort_index()
        # t0 = first regular-way trading day = first yfinance row.
        m = compute_event_metrics(s, spy, first_trade_index=0)
        if m is None:
            # distinguish short history from glitch/edge for the data-wall report.
            if len(s) < NEED_HI + 3:
                short += 1
            else:
                glitch_or_edge += 1
            continue
        # honor the pre-registered first-trade span: 2015..2025-03.
        if not (date(2015, 1, 1) <= m.first_trade_date <= date(2025, 3, 31)):
            short += 1
            continue
        metrics.append(m)
        used += 1
        # same-name placebo: random windows starting well AFTER the event window.
        placebo.extend(
            placebo_cars(
                s,
                spy,
                window_len=21,
                n_draws=PLACEBO_DRAWS_PER_NAME,
                rng=rng,
                min_start=MIN_PLACEBO_GAP_TD,
            )
        )
    return Collected(metrics, used, no_price, short, glitch_or_edge, placebo)


def _placebo_study(values: list[float], label: str):
    return aggregate(
        [
            EventMetrics(
                ticker="placebo",
                first_trade_date=date(2000, 1, 1),
                car_p1_p21=v,
                car_p1_p63=v,
                car_p0_p21=v,
            )
            for v in values
        ],
        label=label,
    )


def run(start_year: int, end_year: int) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    if PRICE_CACHE.exists():
        with contextlib.suppress(Exception):
            _PRICE_CACHE.update(pd.read_pickle(PRICE_CACHE))
            log.info("price_cache.loaded", n=len(_PRICE_CACHE))

    events = fetch_universe(start_year, end_year)
    emit("\n=== T42 SPIN-OFF POST-EVENT DRIFT — forced-selling underpricing ===")
    emit(f"universe: {len(events)} distinct 10-12B filers with a ticker, {start_year}-{end_year}")
    emit(f"PRIMARY window={PRIMARY_WINDOW} (t0+1..t0+21)  round-trip cost={ROUND_TRIP_COST:.4f}")

    spy = _download("SPY", date(2014, 1, 1), date(2025, 6, 30))
    if spy is None:
        raise SystemExit("FATAL: could not download SPY — no market proxy.")

    rng = random.Random(20260615)
    col = collect(events, spy, rng)

    emit("\n--- DATA WALL (count, never hide) ---")
    emit(f"universe filers (w/ ticker) : {len(events)}")
    emit(f"usable spincos              : {col.used}")
    emit(f"dropped: no/empty price      : {col.no_price}")
    emit(f"dropped: short history       : {col.short}")
    emit(f"dropped: glitch / edge       : {col.glitch_or_edge}")

    if col.used < 30:
        emit("\n!!! N < 30 usable spincos — see kill criteria; insufficient free data.")

    _report(col.metrics, "SPINCO COHORT (all)")

    # --- placebo: same-name later windows + pooled random (name, date) pool ---
    pooled: list[float] = []
    names = list({m.ticker for m in col.metrics})
    rng2 = random.Random(777)
    draws_per = max(1, POOLED_PLACEBO_DRAWS // max(len(names), 1))
    for tk in names:
        s = _download(tk, date(2015, 1, 1), date(2025, 6, 30))
        if s is None:
            continue
        pooled.extend(
            placebo_cars(s, spy, window_len=21, n_draws=draws_per, rng=rng2, min_start=80)
        )

    same_pl = _placebo_study(col.same_name_placebo, "PLACEBO same-name post-event")
    pooled_pl = _placebo_study(pooled, "PLACEBO pooled random windows")
    for pl_res in (same_pl, pooled_pl):
        pw = pl_res.windows[PRIMARY_WINDOW]
        emit(f"\n=== {pl_res.label} (N={pw.n}) ===")
        emit(f"  {PRIMARY_WINDOW}: mean={pw.mean:+.4f} median={pw.median:+.4f} t={pw.t_stat:+.2f}")

    # use the pooled placebo (broadest control) in the gate.
    placebo_window = pooled_pl.windows[PRIMARY_WINDOW]

    # --- IS / OOS decay split ---
    is_m, oos_m = split_is_oos(col.metrics)
    is_res = aggregate(is_m, label=f"COHORT IS {start_year}-2019")
    oos_res = aggregate(oos_m, label="COHORT OOS 2020-2025")
    _report(is_m, is_res.label)
    _report(oos_m, oos_res.label)

    all_res = aggregate(col.metrics, label="COHORT (all)")
    p_all = all_res.windows[PRIMARY_WINDOW]
    e = is_res.windows[PRIMARY_WINDOW]
    la = oos_res.windows[PRIMARY_WINDOW]
    emit(f"\n=== DECAY TEST (primary {PRIMARY_WINDOW}, after-cost) ===")
    emit(f"ALL : gross={p_all.mean:+.4f} net={after_cost_mean(p_all):+.4f} t={p_all.t_stat:+.2f} N={p_all.n}")
    emit(f"IS  {start_year}-2019: net={after_cost_mean(e):+.4f} t={e.t_stat:+.2f} N={e.n}")
    emit(f"OOS 2020-2025:       net={after_cost_mean(la):+.4f} t={la.t_stat:+.2f} N={la.n}")

    # --- top-5 contributor robustness ---
    drop5 = drop_top_contributors(col.metrics, k=5).windows[PRIMARY_WINDOW]
    emit("\n=== TOP-5 DROP (does the edge survive losing its 5 biggest names?) ===")
    emit(f"drop-top5: gross={drop5.mean:+.4f} net={after_cost_mean(drop5):+.4f} t={drop5.t_stat:+.2f} N={drop5.n}")

    # --- 2x friction stress ---
    emit("\n=== FRICTION STRESS (primary) ===")
    for cost in (ROUND_TRIP_COST, 2 * ROUND_TRIP_COST):
        emit(f"  round-trip={cost:.4f}: net={after_cost_mean(p_all, round_trip=cost):+.4f}")

    # --- gate ---
    emit(f"\n=== PRE-REGISTERED GATE (after-cost, PRIMARY={PRIMARY_WINDOW}) ===")
    gate = evaluate_gate(all_res, is_res, oos_res, placebo_window)
    for r in gate.reasons:
        emit(f"  {r}")
    emit(f"\nGATE: {'PASS' if gate.passed else 'FAIL — idea killed / null result'}")

    RESULTS_TXT.write_text("\n".join(_LINES) + "\n")
    with contextlib.suppress(Exception):
        pd.to_pickle(_PRICE_CACHE, PRICE_CACHE)
    log.info("results.written", path=str(RESULTS_TXT))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2015)
    p.add_argument("--end", type=int, default=2025)
    args = p.parse_args()
    run(args.start, args.end)


if __name__ == "__main__":
    main()
