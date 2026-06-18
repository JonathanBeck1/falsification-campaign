#!/usr/bin/env python
"""Prepare a JSON batch of events (with 8-K + news pre-fetched) for Claude sub-agents.

Usage:
  TRADER_SEC_USER_AGENT=... .venv/bin/python scripts/catalog_batch_for_claude.py \
    --batch-size 30 --batch-index 0 --out /tmp/batch_0.json

Each batch is a JSON list of dicts; each dict has the event metadata + 8-K +
news context. A Claude sub-agent reads it and returns the classifications as a
JSON list, which scripts/catalog_apply_claude_batch.py then appends to the
catalog parquet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Ensure SEC user-agent is set before edgartools is touched
os.environ.setdefault("TRADER_SEC_USER_AGENT", "catalyst-research you@example.com")

from trader.catalog.build import (  # noqa: E402
    DEFAULT_THRESHOLD,
    already_classified,
    detect_events,
    fetch_8k_for_event,
    load_catalog,
)

CATALOG_PATH = ROOT / "output" / "catalysts" / "news_catalog.parquet"
CLAUDE_CATALOG_PATH = ROOT / "output" / "catalysts" / "news_catalog_claude.parquet"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--batch-index", type=int, default=0,
                        help="Which batch of size N to extract (0=first).")
    parser.add_argument("--out", required=True)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    events = detect_events(threshold=args.threshold)
    codex_done = load_catalog(CATALOG_PATH)
    claude_done = load_catalog(CLAUDE_CATALOG_PATH)
    pending = [
        e for e in events
        if not (already_classified(codex_done, e.ticker, e.date)
                or already_classified(claude_done, e.ticker, e.date))
    ]
    start = args.batch_index * args.batch_size
    end = start + args.batch_size
    chunk = pending[start:end]

    rows = []
    for ev in chunk:
        filings = fetch_8k_for_event(ev.ticker, ev.date)
        rows.append({
            "ticker": ev.ticker,
            "date": ev.date.isoformat(),
            "daily_return": ev.daily_return,
            "abs_return": ev.abs_return,
            "spy_return": ev.spy_return,
            "spy_excess": ev.spy_excess,
            "direction": ev.direction,
            "filings": [
                {"filing_date": f["filing_date"], "items": f["items"],
                 "text_excerpt": f["text_excerpt"][:1500]}
                for f in filings[:3]
            ],
            "news": [],   # Alpaca keys not available; classifier works on 8-K only
        })

    Path(args.out).write_text(json.dumps(rows, indent=2))
    print(f"wrote {args.out}: {len(rows)} events (batch {args.batch_index}, "
          f"size {args.batch_size}, pending before this batch: {len(pending)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
