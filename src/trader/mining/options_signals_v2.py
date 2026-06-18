"""Signal families built from QQQ v2 option-derived features.

Displayed depth, volatility-of-volatility, skew, put/call size, term curvature,
and microstructure features are expanded into trend, contrarian, and rolling
median regime variants that trade the QQQ underlying on the following day.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd

from trader.mining.strategies import Variant

FEATURES_V2 = (
    "gex_depth_proxy",
    "vol_of_vol_20",
    "skew_25d",
    "pc_size_ratio",
    "term_curvature",
    "avg_spread_pct",
    "depth_imbalance",
)


def _variant(name: str, family: str, position: pd.Series, qqq_ret: pd.Series) -> Variant:
    daily = (position.shift(1) * qqq_ret).dropna()
    return Variant(name, "QQQ", family, daily)


def generate_option_variants_v2(features: pd.DataFrame) -> Iterator[Variant]:
    qqq_ret = features["spot"].astype(float).pct_change()
    for fname in FEATURES_V2:
        if fname not in features:
            continue
        feat = features[fname].astype(float)
        for w in (20, 50):
            mean = feat.rolling(w).mean()
            std = feat.rolling(w).std(ddof=0).replace(0.0, np.nan)
            z = (feat - mean) / std
            for d, tag in ((1, "trend"), (-1, "contra")):
                pos = pd.Series(np.sign(d * z), index=feat.index).fillna(0.0)
                yield _variant(f"optv2_{fname}_z{w}_{tag}", f"optv2_{fname}", pos, qqq_ret)
            med = feat.rolling(w).median()
            base = (feat < med).astype(float) * 2 - 1
            for d, tag in ((1, "lowlong"), (-1, "highlong")):
                pos = (d * base).fillna(0.0)
                yield _variant(f"optv2_{fname}_reg{w}_{tag}", f"optv2_{fname}", pos, qqq_ret)
