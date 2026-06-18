#!/usr/bin/env python
"""Extract daily QQQ option-derived features from the lake and cache to parquet."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
from trader.mining.options_features import extract_features  # noqa: E402

OUT = ROOT / "output" / "catalysts" / "qqq_option_features.parquet"
df = extract_features(date(2020, 1, 1), date(2026, 6, 6))
OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(OUT)
print(f"wrote {OUT}: {len(df)} days, cols {list(df.columns)}")
print(df.dropna().tail(3).round(4).to_string())
