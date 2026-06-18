#!/usr/bin/env python
"""Run the cross-sectional strategy-mining lab on liquid ETFs."""

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

from trader.mining.cross_sectional import generate_cross_sectional_variants  # noqa: E402
from trader.mining.lab import LabReport, format_report, run_lab  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

TICKERS: tuple[str, ...] = (
    "EEM",
    "EFA",
    "EWZ",
    "GLD",
    "HYG",
    "IEF",
    "IJR",
    "IVV",
    "IWM",
    "IYT",
    "JNK",
    "KRE",
    "QQQ",
    "SLV",
    "SPY",
    "TLT",
    "USO",
    "VEA",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    "XOP",
)
START = "2010-01-01"
END = "2026-06-06"
SPLIT = "2019-01-01"
REPORT = ROOT / "research" / "cross_sectional_lab_report.md"
JSON_OUT = ROOT / "output" / "catalysts" / "cross_sectional_lab.json"


def fetch(ticker: str) -> pd.Series | None:
    """Fetch adjusted closes, returning None when a ticker is unavailable."""
    try:
        import yfinance as yf

        frame = yf.download(
            ticker,
            start=START,
            end=END,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if frame is None or frame.empty:
            return None
        if isinstance(frame.columns, pd.MultiIndex):
            frame = frame.droplevel(axis=1, level=1)
        close = frame["Close"].dropna()
        close.index = pd.DatetimeIndex(close.index)
        close.name = ticker
        return close if len(close) else None
    except Exception as exc:
        log.warning("cross_sectional_fetch_failed", ticker=ticker, error=str(exc))
        return None


def _write_json(report: LabReport) -> None:
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "n_trials": report.n_trials,
        "split": report.split,
        "expected_false_winners_p05": round(report.expected_false_winners_p05, 1),
        "best": asdict(report.best) if report.best else None,
        "best_dsr": report.best_dsr,
        "best_deflated_sharpe": report.best_deflated_sharpe,
        "n_survivors": len(report.oos_confirmed),
        "survivors": [asdict(score) for score in report.oos_confirmed],
        "leaderboard": [asdict(score) for score in report.leaderboard],
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    prices: dict[str, pd.Series] = {}
    for ticker in TICKERS:
        close = fetch(ticker)
        if close is not None:
            prices[ticker] = close
        log.info("cross_sectional_ticker_loaded", ticker=ticker, days=0 if close is None else len(close))

    variants = list(generate_cross_sectional_variants(prices))
    log.info("cross_sectional_lab_started", variants=len(variants), tickers=len(prices))
    report = run_lab(variants, split=SPLIT)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(format_report(report), encoding="utf-8")
    _write_json(report)
    log.info(
        "cross_sectional_lab_complete",
        report=str(REPORT),
        json=str(JSON_OUT),
        trials=report.n_trials,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
