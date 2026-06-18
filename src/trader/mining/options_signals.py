"""Signal families built from QQQ option-derived features.

Each feature (atm_vol, put_skew, term_slope) is turned into QQQ timing signals two
ways — z-score (trend vs contrarian) and regime (above/below rolling median) — and
expanded over windows. The signals trade the QQQ UNDERLYING (position applied to
next day's spot return). Everything flows into the same deflated-Sharpe + OOS lab,
so any apparent edge is multiple-testing-corrected. These inputs are differentiated
(they require the options data most retail miners lack).
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd

from trader.mining.strategies import Variant

FEATURES = ("atm_vol", "put_skew", "term_slope")


def _variant(name: str, family: str, position: pd.Series, qqq_ret: pd.Series) -> Variant:
    daily = (position.shift(1) * qqq_ret).dropna()
    return Variant(name, "QQQ", family, daily)


def generate_option_variants(features: pd.DataFrame) -> Iterator[Variant]:
    qqq_ret = features["spot"].astype(float).pct_change()
    for fname in FEATURES:
        if fname not in features:
            continue
        feat = features[fname].astype(float)
        for w in (10, 20, 50, 100):
            mean = feat.rolling(w).mean()
            std = feat.rolling(w).std(ddof=0).replace(0.0, np.nan)
            z = (feat - mean) / std
            for d, tag in ((1, "trend"), (-1, "contra")):
                pos = pd.Series(np.sign(d * z), index=feat.index).fillna(0.0)
                yield _variant(f"opt_{fname}_z{w}_{tag}", f"opt_{fname}", pos, qqq_ret)
            med = feat.rolling(w).median()
            for d, tag in ((1, "lowlong"), (-1, "highlong")):
                # lowlong: long QQQ when feature is BELOW its median (e.g. low vol / low skew)
                base = (feat < med).astype(float) * 2 - 1   # +1 below median, -1 above
                pos = (d * base).fillna(0.0)
                yield _variant(f"opt_{fname}_reg{w}_{tag}", f"opt_{fname}", pos, qqq_ret)
