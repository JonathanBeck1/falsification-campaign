"""Run the pre-registered T39 index-reconstitution (announce->effective) study.

Pre-registration: research/index_reconstitution_preregistration.md.

Fetches the maintained S&P 500 constituent-snapshot CSV, diffs it into
add/delete events (effective dates — the reliable part), proxies the announcement
at effective - ANNOUNCE_LEAD_TD trading days, downloads prices (yfinance) + SPY,
computes the market-adjusted announce->effective CAR, runs a same-name placebo,
applies the additions gate after costs, and prints the IS (2010-2017) vs OOS
(2018-2025) decay split plus a K in {3,7} robustness band. Honestly counts
deletions dropped for survivorship.

Usage:
    .venv/bin/python scripts/run_index_reconstitution_study.py
    .venv/bin/python scripts/run_index_reconstitution_study.py --start 2010 --split 2018
"""

from __future__ import annotations

import argparse
import contextlib
import random
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog
import yfinance as yf

from trader.catalysts.index_reconstitution import (
    ANNOUNCE_LEAD_TD,
    PRIMARY_WINDOW,
    ROUND_TRIP_COST,
    EventMetrics,
    IndexChange,
    after_cost_mean,
    aggregate,
    compute_event_metrics,
    evaluate_gate,
    load_changes,
    placebo_cars,
    split_is_oos,
)

warnings.filterwarnings("ignore")
log = structlog.get_logger("index_reconstitution.runner")

PAD_DAYS = 70  # calendar days of price padding each side of the event window
PLACEBO_DRAWS_PER_NAME = 5  # random non-event windows per cohort name
OUT_DIR = Path(__file__).resolve().parents[1] / "data"
# share the rebalance study's warm price cache (same tickers, same loader)
CACHE = OUT_DIR / "index_rebalance_prices.pkl"
RESULTS_TXT = OUT_DIR / "index_reconstitution_results.txt"

_LINES: list[str] = []
_PRICE_CACHE: dict[str, pd.Series | None] = {}


def emit(line: str = "") -> None:
    print(line, flush=True)
    _LINES.append(line)


def _download(ticker: str, start: date, end: date) -> pd.Series | None:
    if ticker in _PRICE_CACHE:
        return _PRICE_CACHE[ticker]
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    except Exception:  # best-effort loader; yfinance raises many error types
        _PRICE_CACHE[ticker] = None
        return None
    if df is None or df.empty or "Close" not in df:
        _PRICE_CACHE[ticker] = None
        return None
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.name = ticker
    out = s if len(s) > 0 else None
    _PRICE_CACHE[ticker] = out
    return out


def _spy_cache(start: date, end: date) -> pd.Series:
    spy = _download("SPY", start, end)
    if spy is None:
        raise SystemExit("FATAL: could not download SPY — no market proxy.")
    return spy


def _report(metrics: list[EventMetrics], label: str) -> None:
    res = aggregate(metrics, label=label)
    emit(f"\n=== {label}  (N={res.n_events}) ===")
    emit(f"{'window':<18}{'mean':>10}{'median':>10}{'%pos':>8}{'t-stat':>9}")
    for name, w in res.windows.items():
        emit(
            f"{name:<18}{w.mean:>+10.4f}{w.median:>+10.4f}"
            f"{w.pct_positive:>8.2f}{w.t_stat:>+9.2f}"
        )


def run(start_year: int, split_year: int) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    if CACHE.exists():
        with contextlib.suppress(Exception):
            _PRICE_CACHE.update(pd.read_pickle(CACHE))
            log.info("price_cache.loaded", n=len(_PRICE_CACHE))

    changes: list[IndexChange] = load_changes()
    lo, hi = date(start_year, 1, 1), date(2025, 12, 31)
    changes = [c for c in changes if lo <= c.effective_date <= hi]
    adds = [c for c in changes if c.kind == "add"]
    dels = [c for c in changes if c.kind == "delete"]
    log.info("filtered", n_add=len(adds), n_del=len(dels), start=start_year)

    spy = _spy_cache(lo - timedelta(days=PAD_DAYS), hi + timedelta(days=PAD_DAYS))

    rng = random.Random(20260614)

    def collect(
        events: list[IndexChange], *, lead: int, gather_placebo: bool
    ) -> tuple[list[EventMetrics], int, int, list[float]]:
        metrics: list[EventMetrics] = []
        placebo: list[float] = []
        missing = used = 0
        for c in events:
            s = _download(
                c.ticker,
                c.effective_date - timedelta(days=PAD_DAYS),
                c.effective_date + timedelta(days=PAD_DAYS),
            )
            if s is None:
                missing += 1
                continue
            try:
                m = compute_event_metrics(
                    s, spy, c.effective_date, kind=c.kind, announce_lead_td=lead
                )
            except Exception:
                log.warning("event.failed", ticker=c.ticker, date=str(c.effective_date))
                m = None
            if m is None:
                missing += 1
                continue
            metrics.append(m)
            used += 1
            if gather_placebo:
                # placebo windows come from a WIDER history pull (same name) so
                # random non-event windows are available away from the event.
                wide = _download(
                    c.ticker,
                    c.effective_date - timedelta(days=900),
                    c.effective_date + timedelta(days=120),
                )
                if wide is not None:
                    placebo.extend(
                        placebo_cars(
                            wide,
                            spy,
                            window_len=lead + 1,
                            n_draws=PLACEBO_DRAWS_PER_NAME,
                            rng=rng,
                        )
                    )
        return metrics, used, missing, placebo

    emit(f"\n=== T39 INDEX RECONSTITUTION — announce->effective (K={ANNOUNCE_LEAD_TD} td) ===")
    emit(f"start={start_year}  IS/OOS split={split_year}  round-trip cost={ROUND_TRIP_COST:.4f}")

    add_metrics, add_used, add_missing, add_placebo = collect(
        adds, lead=ANNOUNCE_LEAD_TD, gather_placebo=True
    )
    del_metrics, del_used, del_missing, _ = collect(
        dels, lead=ANNOUNCE_LEAD_TD, gather_placebo=False
    )

    emit("\n--- DATA WALL (count, don't hide) ---")
    emit(f"additions: {len(adds)} events, {add_used} usable, {add_missing} dropped (no/short/glitch)")
    emit(
        f"deletions: {len(dels)} events, {del_used} usable, {del_missing} dropped "
        f"({100 * del_missing / max(len(dels), 1):.0f}% purged — yfinance survivorship)"
    )

    _report(add_metrics, "ADDITIONS (all)")
    _report(del_metrics, "DELETIONS (all, survivor-biased — NOT in verdict)")

    # placebo aggregate (additions): random non-event windows on the same names.
    placebo_res = aggregate(
        [
            EventMetrics(
                ticker="placebo",
                effective_date=date(2000, 1, 1),
                t0_date=date(2000, 1, 1),
                kind="add",
                car_announce_eff=v,
                car_announce_m1=v,
                car_eff_p5=0.0,
            )
            for v in add_placebo
        ],
        label="PLACEBO (additions, same names, random windows)",
    )
    pl = placebo_res.windows[PRIMARY_WINDOW]
    emit(f"\n=== PLACEBO (N={pl.n}) ===")
    emit(f"  {PRIMARY_WINDOW}: mean={pl.mean:+.4f} median={pl.median:+.4f} t={pl.t_stat:+.2f}")

    # IS / OOS decay split on additions.
    is_add, oos_add = split_is_oos(add_metrics, split_year=split_year)
    is_res = aggregate(is_add, label=f"ADDITIONS IS {start_year}-{split_year - 1}")
    oos_res = aggregate(oos_add, label=f"ADDITIONS OOS {split_year}-2025")
    _report(is_add, is_res.label)
    _report(oos_add, oos_res.label)

    all_res = aggregate(add_metrics, label="ADDITIONS (all)")
    p_all = all_res.windows[PRIMARY_WINDOW]
    e = is_res.windows[PRIMARY_WINDOW]
    la = oos_res.windows[PRIMARY_WINDOW]
    emit(f"\n=== DECAY TEST (primary {PRIMARY_WINDOW}, additions, after-cost) ===")
    emit(
        f"ALL   : gross={p_all.mean:+.4f} net={after_cost_mean(p_all):+.4f} "
        f"t={p_all.t_stat:+.2f} N={p_all.n}"
    )
    emit(f"IS  {start_year}-{split_year - 1}: net={after_cost_mean(e):+.4f} t={e.t_stat:+.2f} N={e.n}")
    emit(f"OOS {split_year}-2025:       net={after_cost_mean(la):+.4f} t={la.t_stat:+.2f} N={la.n}")

    # K-band robustness (report only; K=5 is the pre-registered primary).
    emit("\n=== K-BAND ROBUSTNESS (announce lead, report-only; primary K=5) ===")
    for k in (3, 7):
        km, _, _, _ = collect(adds, lead=k, gather_placebo=False)
        kr = aggregate(km, label=f"K={k}").windows[PRIMARY_WINDOW]
        emit(f"K={k}: gross={kr.mean:+.4f} net={after_cost_mean(kr):+.4f} t={kr.t_stat:+.2f} N={kr.n}")

    emit("\n=== PRE-REGISTERED GATE (additions, after-cost, PRIMARY=announce->effective) ===")
    gate = evaluate_gate(all_res, is_res, oos_res, pl)
    for r in gate.reasons:
        emit(f"  {r}")
    emit(f"\nGATE: {'PASS' if gate.passed else 'FAIL — idea killed / null result'}")

    RESULTS_TXT.write_text("\n".join(_LINES) + "\n")
    with contextlib.suppress(Exception):
        pd.to_pickle(_PRICE_CACHE, CACHE)
    log.info("results.written", path=str(RESULTS_TXT), cache=str(CACHE))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2010)
    p.add_argument("--split", type=int, default=2018)
    args = p.parse_args()
    run(args.start, args.split)


if __name__ == "__main__":
    main()
