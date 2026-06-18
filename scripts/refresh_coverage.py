#!/usr/bin/env python
"""Refresh output/catalysts/data_coverage.json from the options backfill ledger.

Reads the main store READ-ONLY (safe to run alongside a live backfill) and writes
the small JSON the dashboard's Data Coverage view reads.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_CANDIDATES = [
    Path("/Volumes/Express 1M2/trader-data/trader.sqlite"),
    Path("/ABSOLUTE/PATH/TO/trades/data/trader.sqlite"),
]
OUT = Path(__file__).resolve().parent.parent / "output" / "catalysts" / "data_coverage.json"


def main() -> int:
    db = next((p for p in DB_CANDIDATES if p.exists()), None)
    if db is None:
        print("store not found (external drive mounted?)")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cov = {}
    for r in con.execute(
        "select ticker, count(*), min(trade_date), max(trade_date), sum(quote_rows) "
        "from option_quote_backfill_ledger where status='done' group by ticker"
    ):
        cov[r[0]] = {"days": r[1], "first": r[2], "last": r[3], "rows": int(r[4] or 0)}
    ref = max((d["days"] for d in cov.values()), default=1)
    for d in cov.values():
        d["pct_of_reference"] = round(100 * d["days"] / ref, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"reference_full_days": ref, "tickers": cov}, indent=2))
    print(f"wrote {OUT}: " + ", ".join(f"{t} {d['pct_of_reference']:.0f}%" for t, d in cov.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
