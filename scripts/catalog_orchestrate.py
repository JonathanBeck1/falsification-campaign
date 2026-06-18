#!/usr/bin/env python
"""One-shot orchestration step. Run from the cron-fire context:

  .venv/bin/python scripts/catalog_orchestrate.py

It:
  1. Applies any /tmp/batch_*_results.json to the unified catalog
  2. Cleans up consumed input + result files
  3. Counts pending events
  4. Reports whether to spawn the next wave (and how many batches)
  5. Prepares up to 8 new batches if needed

The actual sub-agent spawn happens OUTSIDE this script (the cron prompt tells
Claude to spawn N agents with the prepared batch files).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

CATALOG = ROOT / "output" / "catalysts" / "news_catalog.parquet"
BATCHES_DIR = ROOT / "output" / "catalysts" / "claude_batches"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-batches", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()

    # 1. Apply any pending results
    apply_out = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/catalog_apply_claude_batches.py"), "--cleanup"],
        capture_output=True, text=True, timeout=120,
    )
    print("=== APPLY ===")
    print((apply_out.stdout + apply_out.stderr).strip()[:800])

    # 2. Count progress
    if CATALOG.exists():
        cat = pd.read_parquet(CATALOG)
        done = len(cat)
        cats = dict(cat.category.value_counts()) if "category" in cat else {}
    else:
        done = 0
        cats = {}
    print("=== STATE ===")
    print(f"unified catalog: {done} events")
    print(f"top categories: {sorted(cats.items(), key=lambda x: -x[1])[:6]}")

    # 3. Detect pending count (cheap — just call detect-only)
    detect = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/run_news_catalog.py"), "--detect-only"],
        capture_output=True, text=True, timeout=60,
    )
    detect_stdout = detect.stdout.strip()
    total = 0
    for tok in detect_stdout.split():
        if tok.isdigit():
            total = int(tok)
            break
    pending = max(0, total - done)
    print(f"detected total: {total}  pending: {pending}")

    # 4. Prepare next batches if catalog isn't complete
    if pending == 0:
        print("=== DONE ===")
        print("catalog complete; stop the cron.")
        return 0

    # Clean any leftover batch files (some may have been consumed already by --cleanup)
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    for old in BATCHES_DIR.glob("batch_*.json"):
        old.unlink()

    n_batches = min(args.target_batches, (pending + args.batch_size - 1) // args.batch_size)
    print("=== PREPARE ===")
    print(f"preparing {n_batches} batches of {args.batch_size} events each")
    for i in range(n_batches):
        out = BATCHES_DIR / f"batch_{i}.json"
        prep = subprocess.run(
            [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/catalog_batch_for_claude.py"),
             "--batch-size", str(args.batch_size),
             "--batch-index", str(i),
             "--out", str(out)],
            capture_output=True, text=True, timeout=180,
        )
        last = prep.stdout.strip().splitlines()[-1] if prep.stdout.strip() else "(no output)"
        print(f"  batch {i}: {last}")

    actual = sorted(BATCHES_DIR.glob("batch_*.json"))
    print("=== READY FOR SPAWN ===")
    print(f"batches ready: {len(actual)}")
    print(f"  next action: spawn {len(actual)} parallel Sonnet sub-agents reading these files")

    # Log a status line to a known file the dashboard / user can tail
    log_line = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "done": done,
        "pending": pending,
        "batches_prepared": len(actual),
    }
    with open(ROOT / "output" / "catalog_orchestration.log", "a") as f:
        f.write(json.dumps(log_line) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
