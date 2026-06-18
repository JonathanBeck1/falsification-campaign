#!/usr/bin/env python
"""Run the cross-asset signals lab with deflated-Sharpe correction.

  .venv/bin/python scripts/run_multi_asset_lab.py
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
from trader.mining.multi_asset import generate_multi_asset_variants  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
logger = structlog.get_logger(__name__)

BASKET = ["SPY", "QQQ", "TLT", "IEF", "GLD", "HYG", "LQD", "UUP", "VIXY", "^VIX"]
START, END, SPLIT = "2010-01-01", "2026-06-06", "2019-01-01"
REPORT = ROOT / "research" / "multi_asset_lab_report.md"
JSON_OUT = ROOT / "output" / "catalysts" / "multi_asset_lab.json"


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

    df = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)
    series = df["Close"].dropna()
    series.index = pd.DatetimeIndex(series.index)
    series.name = ticker.lstrip("^")
    return series if len(series) else None


def main() -> int:
    prices: dict[str, pd.Series] = {}
    for ticker in BASKET:
        try:
            series = fetch(ticker)
        except Exception as exc:
            logger.warning(
                "multi_asset_fetch_failed",
                ticker=ticker,
                error=str(exc),
            )
            series = None
        key = ticker.lstrip("^")
        if series is not None:
            prices[key] = series
        print(f"  {ticker}: {0 if series is None else len(series)} days", flush=True)
    variants = list(generate_multi_asset_variants(prices))
    print(
        f"\nGenerated {len(variants)} variants across {len(prices)} tickers. Running lab...",
        flush=True,
    )
    rep = run_lab(variants, split=SPLIT)
    REPORT.write_text(format_report(rep))
    _write_json(rep)
    print("\n" + format_report(rep))
    print(f"Report: {REPORT}\nDashboard JSON: {JSON_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
