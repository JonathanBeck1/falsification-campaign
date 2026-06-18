#!/usr/bin/env python
"""Run the intraday QQQ strategy-mining lab."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.mining.intraday_qqq import (  # noqa: E402
    CACHE_PATH,
    compute_daily_features,
    generate_intraday_variants,
    load_intraday_qqq,
)
from trader.mining.lab import LabReport, format_report, run_lab  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger(__name__)

REPORT = ROOT / "research" / "intraday_lab_report.md"
JSON_OUT = ROOT / "output" / "catalysts" / "intraday_lab.json"
SPLIT = "2024-01-01"


def _write_json(report: LabReport) -> None:
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "n_trials": report.n_trials,
        "split": report.split,
        "expected_false_winners_p05": round(
            report.expected_false_winners_p05,
            1,
        ),
        "best": asdict(report.best) if report.best else None,
        "best_dsr": report.best_dsr,
        "best_deflated_sharpe": report.best_deflated_sharpe,
        "n_survivors": len(report.oos_confirmed),
        "survivors": [asdict(score) for score in report.oos_confirmed],
        "leaderboard": [asdict(score) for score in report.leaderboard],
    }
    JSON_OUT.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    minute_df = load_intraday_qqq()
    if minute_df.empty:
        print("No minute data available (lake missing and cache empty); aborting.")
        return 1

    features = compute_daily_features(minute_df)
    variants = generate_intraday_variants(features)
    print(
        f"Generated {len(variants)} intraday variants "
        f"from {len(features)} session days."
    )
    report = run_lab(variants, split=SPLIT)
    formatted = format_report(report)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(formatted, encoding="utf-8")
    _write_json(report)
    print(formatted)
    log.info(
        "intraday_lab_complete",
        cache=str(CACHE_PATH),
        report=str(REPORT),
        json=str(JSON_OUT),
        trials=report.n_trials,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
