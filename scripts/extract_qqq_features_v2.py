#!/usr/bin/env python
"""Extract v2 daily QQQ option features (gex/skew25/pc_size_ratio/term_curvature/microstructure)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
from trader.mining.options_features_v2 import extract_features_v2  # noqa: E402

OUT = ROOT / "output" / "catalysts" / "qqq_option_features_v2.parquet"
df = extract_features_v2(
    date(2020, 1, 1),
    date(2026, 6, 6),
    base_features_path=ROOT / "output" / "catalysts" / "qqq_option_features.parquet",
)
OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(OUT)
print(f"wrote {OUT}: {len(df)} days, cols {list(df.columns)}")
print(df.dropna().tail(3).round(4).to_string())
