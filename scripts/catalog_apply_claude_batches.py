#!/usr/bin/env python
"""Apply Claude sub-agent batch results (/tmp/batch_N_results.json) to the
catalog parquet.

- Reads every /tmp/batch_*_results.json file
- Validates schema, drops malformed rows
- Appends to output/catalysts/news_catalog_claude.parquet (Claude-side catalog)
- Optionally merges into the unified output/catalysts/news_catalog.parquet
  so the dashboard sees everything in one place
- Deletes the /tmp/batch_*_results.json files when done
- Also deletes the consumed input batches (output/catalysts/claude_batches/batch_*.json)
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_CATALOG = ROOT / "output" / "catalysts" / "news_catalog_claude.parquet"
UNIFIED_CATALOG = ROOT / "output" / "catalysts" / "news_catalog.parquet"

REQUIRED_FIELDS = (
    "ticker", "date", "daily_return", "category", "confidence",
)
OPTIONAL_FIELDS = (
    "abs_return", "direction", "spy_return", "spy_excess",
    "subcategory", "article_relative_timing", "brief_explanation",
    "is_market_wide", "evidence_snippet", "n_filings_8k", "n_news_articles",
    "model", "input_tokens", "output_tokens", "cost_usd",
)


def _validate(row: dict) -> dict | None:
    for f in REQUIRED_FIELDS:
        if f not in row:
            return None
    out: dict = {f: row[f] for f in REQUIRED_FIELDS}
    for f in OPTIONAL_FIELDS:
        out[f] = row.get(f)
    out["classified_at"] = datetime.now().isoformat(timespec="seconds")
    out.setdefault("model", "claude-sonnet-4-6")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-glob", default="/tmp/batch_*_results.json")
    parser.add_argument("--cleanup", action="store_true",
                        help="Delete consumed input + result JSON files when done.")
    args = parser.parse_args()

    files = sorted(glob.glob(args.results_glob))
    if not files:
        print("no result files found")
        return 0

    new_rows: list[dict] = []
    parse_errs = 0
    for f in files:
        try:
            data = json.loads(Path(f).read_text())
        except Exception as exc:
            print(f"  ERR {f}: parse failed: {exc}")
            parse_errs += 1
            continue
        if not isinstance(data, list):
            print(f"  ERR {f}: not a list")
            parse_errs += 1
            continue
        for row in data:
            v = _validate(row)
            if v is not None:
                new_rows.append(v)

    if not new_rows:
        print("no valid rows extracted")
        return 1

    # Append to Claude catalog
    CLAUDE_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(CLAUDE_CATALOG) if CLAUDE_CATALOG.exists() else pd.DataFrame()
    combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
    combined = combined.drop_duplicates(subset=["ticker", "date"], keep="first")
    tmp = CLAUDE_CATALOG.with_suffix(CLAUDE_CATALOG.suffix + ".tmp")
    combined.to_parquet(tmp)
    tmp.replace(CLAUDE_CATALOG)

    # Merge into unified catalog (so dashboard sees everything)
    unified_existing = pd.read_parquet(UNIFIED_CATALOG) if UNIFIED_CATALOG.exists() else pd.DataFrame()
    unified_combined = pd.concat([unified_existing, pd.DataFrame(new_rows)], ignore_index=True)
    unified_combined = unified_combined.drop_duplicates(subset=["ticker", "date"], keep="first")
    tmp = UNIFIED_CATALOG.with_suffix(UNIFIED_CATALOG.suffix + ".tmp")
    unified_combined.to_parquet(tmp)
    tmp.replace(UNIFIED_CATALOG)

    print(f"applied {len(new_rows)} new rows (parse errors: {parse_errs})")
    print(f"  claude catalog: {len(combined)} total")
    print(f"  unified catalog: {len(unified_combined)} total")

    if args.cleanup:
        # Identify which batch indexes were processed and delete inputs
        import re
        processed_idxs = set()
        for f in files:
            m = re.search(r"batch_(\d+)_results\.json$", f)
            if m:
                processed_idxs.add(int(m.group(1)))
        for f in files:
            with contextlib.suppress(OSError):
                Path(f).unlink()
        for idx in processed_idxs:
            p = ROOT / "output" / "catalysts" / "claude_batches" / f"batch_{idx}.json"
            with contextlib.suppress(OSError):
                p.unlink()
        print(f"  cleaned up {len(files)} result files + {len(processed_idxs)} input batches")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
