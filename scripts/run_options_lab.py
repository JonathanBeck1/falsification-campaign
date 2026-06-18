#!/usr/bin/env python
"""Mine QQQ option-derived signals (vol/skew/term-structure) with the
deflated-Sharpe + out-of-sample correction. Differentiated-data edge hunt."""
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
from trader.mining.lab import format_report, run_lab  # noqa: E402
from trader.mining.options_signals import generate_option_variants  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
FEATURES = ROOT / "output" / "catalysts" / "qqq_option_features.parquet"
REPORT = ROOT / "research" / "options_lab_report.md"
JSON_OUT = ROOT / "output" / "catalysts" / "options_lab.json"
SPLIT = "2023-06-01"

def main() -> int:
    if not FEATURES.exists():
        print("run scripts/extract_qqq_features.py first", file=sys.stderr)
        return 1
    feats = pd.read_parquet(FEATURES)
    variants = list(generate_option_variants(feats))
    print(f"QQQ option-signal variants: {len(variants)} (features over {len(feats)} days)")
    rep = run_lab(variants, split=SPLIT)
    REPORT.write_text(format_report(rep))
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "n_trials": rep.n_trials, "split": rep.split,
        "expected_false_winners_p05": round(rep.expected_false_winners_p05, 1),
        "best": asdict(rep.best) if rep.best else None,
        "best_dsr": rep.best_dsr, "best_deflated_sharpe": rep.best_deflated_sharpe,
        "n_survivors": len(rep.oos_confirmed),
        "survivors": [asdict(s) for s in rep.oos_confirmed],
        "leaderboard": [asdict(s) for s in rep.leaderboard],
    }
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, indent=2))
    print(format_report(rep))
    print(f"JSON: {JSON_OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
