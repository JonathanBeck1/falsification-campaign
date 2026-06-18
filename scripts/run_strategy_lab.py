#!/usr/bin/env python
"""Mine hundreds of strategy variants on a basket of liquid ETFs, with the
deflated-Sharpe multiple-testing correction so the result is honest.

  .venv/bin/python scripts/run_strategy_lab.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.mining.lab import LabReport, format_report, run_lab  # noqa: E402
from trader.mining.strategies import generate_variants  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))

BASKET = ["SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "TLT", "IEF",
          "GLD", "HYG", "XLF", "XLK", "XLE", "XLV", "XLU"]
START, END, SPLIT = "2010-01-01", "2026-06-06", "2019-01-01"
REPORT = ROOT / "research" / "strategy_lab_report.md"
JSON_OUT = ROOT / "output" / "catalysts" / "strategy_lab.json"


def _write_json(rep: LabReport) -> None:
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "n_trials": rep.n_trials,
        "split": rep.split,
        "expected_false_winners_p05": round(rep.expected_false_winners_p05, 1),
        "best": asdict(rep.best) if rep.best else None,
        "best_dsr": rep.best_dsr,
        "best_deflated_sharpe": rep.best_deflated_sharpe,
        "n_survivors": len(rep.oos_confirmed),
        "survivors": [asdict(s) for s in rep.oos_confirmed],
        "leaderboard": [asdict(s) for s in rep.leaderboard],
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2))


def fetch(ticker: str) -> pd.Series | None:
    import yfinance as yf
    df = yf.download(ticker, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)
    s = df["Close"].dropna()
    s.index = pd.DatetimeIndex(s.index)
    s.name = ticker
    return s if len(s) else None


def main() -> int:
    prices = {}
    for t in BASKET:
        s = fetch(t)
        if s is not None:
            prices[t] = s
        print(f"  {t}: {0 if s is None else len(s)} days", flush=True)
    variants = list(generate_variants(prices))
    print(f"\nGenerated {len(variants)} variants across {len(prices)} tickers. Running lab...", flush=True)
    rep = run_lab(variants, split=SPLIT)
    REPORT.write_text(format_report(rep))
    _write_json(rep)
    print("\n" + format_report(rep))
    print(f"Report: {REPORT}\nDashboard JSON: {JSON_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
