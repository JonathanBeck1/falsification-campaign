#!/usr/bin/env python
"""Diagnostic for T26 — show that the options-implied carry q* IS borrow + dividend.

NOT a gating artifact; a one-off MECHANISM diagnostic requested in the T26
correction. It (1) recomputes the per-name median implied carry q* from the lake
exactly as ``run_putcall_parity_borrow_study.py`` does, (2) fetches each name's
trailing dividend yield over the study window from yfinance, (3) reports
corr(div_yield, q*), the dividend-payer vs zero-div q* gap, and the
dividend-netted implied borrow b = q* - div_yield (which should be ~0). This is
the evidence that the "implied borrow" sort is a DIVIDEND/factor tilt, not a
short-supply borrow signal.

Usage:
    .venv/bin/python scripts/diag_putcall_dividend.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.putcall_parity_borrow import median, name_date_borrow  # noqa: E402
from trader.catalysts.vol_surface_data import load_option_quotes  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

UNIVERSE = [
    "ADBE", "AMAT", "AMD", "AVGO", "BKNG", "COST", "CSCO", "GOOG", "GOOGL",
    "HON", "INTU", "ISRG", "LIN", "LRCX", "META", "MU", "NFLX", "PEP", "QCOM",
    "REGN", "TMUS", "TSLA", "TXN", "VRTX",
]
SINCE = date(2022, 1, 1)
UNTIL = date(2026, 6, 13)


def per_name_median_qstar() -> dict[str, float]:
    """Median implied carry q* per name, recomputed from the lake (study-identical)."""

    out: dict[str, float] = {}
    for ticker in UNIVERSE:
        quotes = load_option_quotes(ticker, SINCE, UNTIL)
        if quotes.empty:
            continue
        samples: list[float] = []
        for td, day_quotes in quotes.groupby(quotes["trade_date"].dt.normalize()):
            nb = name_date_borrow(day_quotes, ticker, td)
            if nb is not None:
                samples.append(nb.implied_borrow)
        if samples:
            out[ticker] = median(samples)
        print(f"  {ticker}: q*median={out.get(ticker, float('nan')) * 1e4:+8.1f} bps "
              f"(n={len(samples)})", flush=True)
    return out


def trailing_dividend_yield() -> dict[str, float]:
    """Avg trailing-12m dividend yield over the study window from yfinance.

    For each name, sum dividends in each trailing-12m window across 2022-2026 and
    divide by the close, then average. Zero for non-payers. Network call.
    """

    import yfinance as yf

    out: dict[str, float] = {}
    for ticker in UNIVERSE:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(start="2021-06-01", end="2026-06-13", auto_adjust=False)
            if hist.empty:
                out[ticker] = 0.0
                continue
            divs = tk.dividends
            if divs is None or len(divs) == 0:
                out[ticker] = 0.0
                continue
            # trailing-12m dividend / close, sampled monthly over the study window
            divs = divs.copy()
            divs.index = pd.to_datetime(divs.index).tz_localize(None)
            close = hist["Close"].copy()
            close.index = pd.to_datetime(close.index).tz_localize(None)
            ys: list[float] = []
            for ts in pd.date_range("2022-01-01", "2026-06-01", freq="MS"):
                ttm = float(divs[(divs.index > ts - pd.Timedelta(days=365)) & (divs.index <= ts)].sum())
                px_window = close[close.index <= ts]
                if len(px_window) == 0 or px_window.iloc[-1] <= 0:
                    continue
                ys.append(ttm / float(px_window.iloc[-1]))
            out[ticker] = float(np.mean(ys)) if ys else 0.0
        except Exception as exc:
            print(f"  div fetch failed {ticker}: {exc}", flush=True)
            out[ticker] = 0.0
        print(f"  {ticker}: div_yield={out[ticker] * 1e4:+8.1f} bps", flush=True)
    return out


def main() -> int:
    print("=== per-name median implied carry q* (from lake) ===", flush=True)
    qstar = per_name_median_qstar()
    print("\n=== trailing dividend yield (yfinance) ===", flush=True)
    div = trailing_dividend_yield()

    names = [t for t in UNIVERSE if t in qstar]
    q = np.array([qstar[t] for t in names])
    d = np.array([div.get(t, 0.0) for t in names])
    b = q - d  # dividend-netted implied borrow

    corr = float(np.corrcoef(d, q)[0, 1]) if len(names) > 2 else float("nan")
    payers = np.array([t for t in names if div.get(t, 0.0) > 1e-4])
    zero = np.array([t for t in names if div.get(t, 0.0) <= 1e-4])
    payer_q = np.mean([qstar[t] for t in payers]) if len(payers) else float("nan")
    zero_q = np.mean([qstar[t] for t in zero]) if len(zero) else float("nan")

    print("\n" + "=" * 70)
    print("MECHANISM: implied carry q* = borrow + dividend")
    print("=" * 70)
    print(f"corr(dividend_yield, q*) = {corr:+.3f}  (n={len(names)} names)")
    print(f"dividend-payer avg q*   = {payer_q * 1e4:+.1f} bps  (n={len(payers)})")
    print(f"zero-dividend avg q*    = {zero_q * 1e4:+.1f} bps  (n={len(zero)})")
    print(f"dividend-netted borrow b = q* - div: mean={np.mean(b) * 1e4:+.1f} bps "
          f"median={np.median(b) * 1e4:+.1f} bps  (should be ~0)")
    print("\nper-name table (bps/yr):")
    print(f"  {'name':6s} {'q*':>9s} {'div_yld':>9s} {'borrow b':>9s}")
    for t in sorted(names, key=lambda x: -qstar[x]):
        print(f"  {t:6s} {qstar[t] * 1e4:+9.1f} {div.get(t, 0.0) * 1e4:+9.1f} "
              f"{(qstar[t] - div.get(t, 0.0)) * 1e4:+9.1f}")
    print(f"\nHON q* (was '-6857 pathological'): {qstar.get('HON', float('nan')) * 1e4:+.1f} bps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
