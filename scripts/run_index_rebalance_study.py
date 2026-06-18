"""Run the pre-registered S&P 500 index-rebalance event study end to end.

Fetches the maintained constituent-snapshot CSV, diffs it into add/delete events,
downloads prices (yfinance) + SPY, computes market-adjusted CARs, aggregates with
t-stats, applies the additions gate, and prints the EARLY (2010-2017) vs RECENT
(2018-2025) decay comparison. Honestly counts deletions dropped for missing
(purged) price data.

Usage:
    .venv/bin/python scripts/run_index_rebalance_study.py
    .venv/bin/python scripts/run_index_rebalance_study.py --start 2010 --split 2018
"""

from __future__ import annotations

import argparse
import contextlib
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog
import yfinance as yf

from trader.catalysts.index_rebalance import (
    EventMetrics,
    IndexChange,
    aggregate,
    compute_event_metrics,
    evaluate_gate,
    load_changes,
)

warnings.filterwarnings("ignore")
log = structlog.get_logger("index_rebalance.runner")

PAD_DAYS = 70  # calendar days of price padding each side of the event window
OUT_DIR = Path(__file__).resolve().parents[1] / "data"
CACHE = OUT_DIR / "index_rebalance_prices.pkl"
RESULTS_TXT = OUT_DIR / "index_rebalance_results.txt"

_LINES: list[str] = []
_PRICE_CACHE: dict[str, pd.Series | None] = {}


def emit(line: str = "") -> None:
    """Print AND retain the line, so results survive stdout buffering."""

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
    if isinstance(s, pd.DataFrame):  # multiindex from yfinance single-ticker
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


def run(start_year: int, split_year: int) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    if CACHE.exists():  # warm the price cache so re-runs are instant
        with contextlib.suppress(Exception):  # corrupt cache is non-fatal
            _PRICE_CACHE.update(pd.read_pickle(CACHE))
            log.info("price_cache.loaded", n=len(_PRICE_CACHE))

    changes: list[IndexChange] = load_changes()
    lo, hi = date(start_year, 1, 1), date(2025, 12, 31)
    changes = [c for c in changes if lo <= c.effective_date <= hi]
    adds = [c for c in changes if c.kind == "add"]
    dels = [c for c in changes if c.kind == "delete"]
    log.info("filtered", n_add=len(adds), n_del=len(dels), start=start_year)

    spy = _spy_cache(lo - timedelta(days=PAD_DAYS), hi + timedelta(days=PAD_DAYS))

    def collect(events: list[IndexChange]) -> tuple[list[EventMetrics], int, int]:
        metrics: list[EventMetrics] = []
        missing = 0
        used = 0
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
                m = compute_event_metrics(s, spy, c.effective_date, kind=c.kind)
            except Exception:  # one bad event must never kill the whole run
                log.warning("event.failed", ticker=c.ticker, date=str(c.effective_date))
                m = None
            if m is None:
                missing += 1
                continue
            metrics.append(m)
            used += 1
        return metrics, used, missing

    emit(f"\n=== Collecting prices (start={start_year}, decay split={split_year}) ===")
    add_metrics, add_used, add_missing = collect(adds)
    del_metrics, del_used, del_missing = collect(dels)

    emit("\n--- DATA WALL (count, don't hide) ---")
    emit(f"additions: {len(adds)} events, {add_used} usable, {add_missing} dropped (no/short data)")
    emit(f"deletions: {len(dels)} events, {del_used} usable, {del_missing} dropped "
          f"({100*del_missing/max(len(dels),1):.0f}% purged — yfinance survivorship)")

    def report(metrics: list[EventMetrics], label: str) -> None:
        res = aggregate(metrics, label=label)
        emit(f"\n=== {label}  (N={res.n_events}) ===")
        emit(f"{'window':<12}{'mean':>10}{'median':>10}{'%pos':>8}{'t-stat':>9}")
        for name, w in res.windows.items():
            emit(f"{name:<12}{w.mean:>+10.4f}{w.median:>+10.4f}{w.pct_positive:>8.2f}{w.t_stat:>+9.2f}")

    report(add_metrics, "ADDITIONS (all)")
    report(del_metrics, "DELETIONS (all, survivor-biased)")

    # Decay / OOS split on additions (the headline).
    add_early = [m for m in add_metrics if m.event_date.year < split_year]
    add_late = [m for m in add_metrics if m.event_date.year >= split_year]
    early_res = aggregate(add_early, label=f"ADDITIONS {start_year}-{split_year-1}")
    late_res = aggregate(add_late, label=f"ADDITIONS {split_year}-2025")
    report(add_early, early_res.label)
    report(add_late, late_res.label)

    all_res = aggregate(add_metrics, label="ADDITIONS (all)")
    emit("\n=== DECAY TEST (primary window car_0_p21, additions) ===")
    e = early_res.windows["car_0_p21"]
    la = late_res.windows["car_0_p21"]
    emit(f"EARLY  {start_year}-{split_year-1}: mean={e.mean:+.4f} t={e.t_stat:+.2f} N={e.n}")
    emit(f"RECENT {split_year}-2025:       mean={la.mean:+.4f} t={la.t_stat:+.2f} N={la.n}")
    if e.mean == e.mean and la.mean == la.mean:
        verdict = "LARGER EARLY (decay consistent w/ prior)" if e.mean > la.mean else "NOT larger early"
        emit(f"decay: {verdict}")

    emit("\n=== PRE-REGISTERED GATE (additions) ===")
    gate = evaluate_gate(all_res, early_res, late_res)
    for r in gate.reasons:
        emit(f"  {r}")
    emit(f"\nGATE: {'PASS' if gate.passed else 'FAIL — idea killed / null result'}")

    # Persist results + warm price cache for fast re-runs.
    RESULTS_TXT.write_text("\n".join(_LINES) + "\n")
    with contextlib.suppress(Exception):  # cache write is best-effort
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
