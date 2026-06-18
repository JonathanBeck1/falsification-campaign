#!/usr/bin/env python
"""Re-run the classical-strategy lab against a small-cap / niche-ETF
universe to test the "capacity-constrained niches" theory after mega-cap
ETFs had zero survivors.

  .venv/bin/python scripts/run_small_universe_lab.py
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

BASKET = ["IJR", "VBR", "IJS", "IWN", "IWO", "SLY", "SLYG", "RWR", "KBWY",
          "SCHH", "AMLP", "MLPX", "BIZD", "VWO", "SCZ", "DGS", "GREK", "KWEB"]
START, END, SPLIT = "2010-01-01", "2026-06-06", "2019-01-01"
REPORT = ROOT / "research" / "small_universe_lab_report.md"
JSON_OUT = ROOT / "output" / "catalysts" / "small_universe_lab.json"


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

    try:
        df = yf.download(
            ticker, start=START, end=END, auto_adjust=True,
            progress=False, threads=False,
        )
    except Exception as err:
        print(f"  {ticker}: FAILED ({err})", flush=True)
        return None
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
    dropped = []
    for t in BASKET:
        s = fetch(t)
        if s is None:
            dropped.append((t, "empty/failed download"))
            print(f"  {t}: DROPPED (empty/failed download)", flush=True)
        elif len(s) < 250:
            dropped.append((t, "short-history"))
            print(f"  {t}: DROPPED (short-history)", flush=True)
        else:
            prices[t] = s
            print(f"  {t}: {len(s)} days", flush=True)
    variants = list(generate_variants(prices))
    print(f"\nGenerated {len(variants)} variants across {len(prices)} tickers. Running lab...", flush=True)
    rep = run_lab(variants, split=SPLIT)
    formatted = format_report(rep)
    coverage = ["", "## Universe coverage", "", "### Kept", ""]
    coverage.extend(f"- {ticker}: {len(series)} days" for ticker, series in prices.items())
    coverage.extend(["", "### Dropped", ""])
    coverage.extend(f"- {ticker}: {reason}" for ticker, reason in dropped)
    REPORT.write_text(formatted + "\n".join(coverage) + "\n")
    _write_json(rep)
    print("\n" + formatted)
    print(f"Report: {REPORT}\nDashboard JSON: {JSON_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
