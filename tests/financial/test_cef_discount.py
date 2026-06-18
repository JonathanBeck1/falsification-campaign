"""Network-free unit tests for the pure CEF discount + glitch-guard logic.

Covers: the discount ratio on raw closes (incl. the verified GAM/XGAMX -17.2%
spot value), price/NAV date alignment (only common dates survive, zero/garbage
NAV dropped), the glitch guard (a >20% price jump with a flat NAV is flagged and
excluded from the clean series), and the resolution-narrowing window math.
"""

from __future__ import annotations

import pandas as pd

from trader.catalysts.cef_discount import (
    compute_discount,
    discount_with_glitch_guard,
    flag_glitch_days,
    resolution_narrowing,
)
from trader.catalysts.tiingo import parse_raw_close


def _series(pairs):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in pairs])
    return pd.Series([v for _, v in pairs], index=idx)


# --------------------------------------------------------------------------- #
# Discount ratio
# --------------------------------------------------------------------------- #


def test_discount_matches_verified_gam_xgamx_spot():
    # Verified live in the prompt: GAM 35.98 / XGAMX 43.47 -> -17.2%.
    price = _series([("2023-01-03", 35.98)])
    nav = _series([("2023-01-03", 43.47)])
    disc = compute_discount(price, nav)
    assert disc.index[0] == pd.Timestamp("2023-01-03")
    assert abs(disc.iloc[0] - (-0.1722)) < 0.0005


def test_discount_aligns_on_common_dates_only():
    price = _series([("2023-01-03", 35.0), ("2023-01-04", 36.0), ("2023-01-05", 37.0)])
    # NAV missing 01-03, extra 01-06 -> only 01-04 and 01-05 overlap.
    nav = _series([("2023-01-04", 40.0), ("2023-01-05", 40.0), ("2023-01-06", 41.0)])
    disc = compute_discount(price, nav)
    assert list(disc.index) == [pd.Timestamp("2023-01-04"), pd.Timestamp("2023-01-05")]
    assert abs(disc.loc["2023-01-04"] - (36.0 / 40.0 - 1)) < 1e-12


def test_discount_drops_nonpositive_nav():
    price = _series([("2023-01-03", 35.0), ("2023-01-04", 36.0)])
    nav = _series([("2023-01-03", 0.0), ("2023-01-04", 40.0)])  # 0 NAV is garbage
    disc = compute_discount(price, nav)
    assert list(disc.index) == [pd.Timestamp("2023-01-04")]


def test_discount_empty_when_no_overlap():
    price = _series([("2023-01-03", 35.0)])
    nav = _series([("2023-02-03", 40.0)])
    assert compute_discount(price, nav).empty


# --------------------------------------------------------------------------- #
# Glitch guard
# --------------------------------------------------------------------------- #


def test_glitch_day_flagged_when_price_jumps_but_nav_flat():
    # Day 3: price +224% (BNY class), NAV moves <2% -> flagged.
    price = _series(
        [("2023-01-03", 10.0), ("2023-01-04", 10.1), ("2023-01-05", 32.7)]
    )
    nav = _series(
        [("2023-01-03", 12.0), ("2023-01-04", 12.05), ("2023-01-05", 12.06)]
    )
    glitches = flag_glitch_days(price, nav)
    assert glitches == [pd.Timestamp("2023-01-05")]


def test_real_discount_move_not_flagged():
    # Price and NAV both move together (real) -> not a glitch.
    price = _series([("2023-01-03", 10.0), ("2023-01-04", 12.5)])
    nav = _series([("2023-01-03", 12.0), ("2023-01-04", 15.0)])  # NAV +25% too
    assert flag_glitch_days(price, nav) == []


def test_glitch_day_excluded_from_clean_series():
    price = _series(
        [("2023-01-03", 10.0), ("2023-01-04", 10.1), ("2023-01-05", 32.7)]
    )
    nav = _series(
        [("2023-01-03", 12.0), ("2023-01-04", 12.05), ("2023-01-05", 12.06)]
    )
    res = discount_with_glitch_guard(price, nav)
    assert res.n_overlap == 3
    assert res.glitch_dates == (pd.Timestamp("2023-01-05"),)
    # raw discount keeps the glitch; clean drops it.
    assert len(res.discount) == 3
    assert pd.Timestamp("2023-01-05") not in res.clean.index
    assert len(res.clean) == 2


# --------------------------------------------------------------------------- #
# Raw-close parsing (the discount uses raw close, not adjClose)
# --------------------------------------------------------------------------- #


def test_parse_raw_close_uses_close_not_adjclose():
    rows = [
        {"date": "2023-01-03T00:00:00.000Z", "close": 35.98, "adjClose": 27.65},
    ]
    s = parse_raw_close(rows, "GAM")
    assert s is not None
    assert s.iloc[0] == 35.98  # raw close, NOT adjClose


def test_parse_raw_close_empty():
    assert parse_raw_close([], "GAM") is None
    assert parse_raw_close("nonsense", "GAM") is None


# --------------------------------------------------------------------------- #
# Resolution narrowing
# --------------------------------------------------------------------------- #


def test_resolution_narrowing_baseline_vs_final():
    # 300 days: discount -0.15 for first 280, then ramps to ~0 over the last 20.
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    vals = [-0.15] * 280 + [(-0.15 + 0.15 * (i + 1) / 20) for i in range(20)]
    clean = pd.Series(vals, index=idx)
    baseline, final = resolution_narrowing(clean)
    assert baseline is not None and final is not None
    # baseline (-250..-60) sits in the flat -0.15 region.
    assert abs(baseline - (-0.15)) < 0.01
    # final 20 days narrowed strongly toward 0.
    assert final > baseline
    assert abs(final) < abs(baseline)


def test_resolution_narrowing_none_when_too_short():
    clean = pd.Series([-0.1, -0.1], index=pd.date_range("2020-01-01", periods=2))
    baseline, final = resolution_narrowing(clean)
    assert baseline is None  # not enough days for the -250..-60 window
    assert final is None  # fewer than 20 days
