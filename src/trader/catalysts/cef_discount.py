"""Pure CEF discount computation + glitch guard for the Phase 5 pilot.

The discount is the whole point of the CEF resolution-selection study: a
closed-end fund trades at ``price`` while its underlying portfolio is worth
``NAV`` per share, and ``discount = price / NAV - 1`` is structurally negative
(funds trade below NAV) for most names. When a fund liquidates/merges, the
discount is *forced* to ~0 at the terminal date — the "resolution-capture"
edge mechanism this pilot is the first direct look at.

Everything here is PURE and network-free. The fetch lives in
``catalysts/tiingo.py`` (``fetch_raw_close``); the pilot script wires the two.

The discount MUST be computed on **raw** (unadjusted) closes for both legs —
see ``tiingo.parse_raw_close`` for why adjusted closes corrupt the ratio.

Glitch guard (brain/32): a vendor adjustment artifact shows up as a huge 1-day
price jump with no matching NAV move (the BNY +224% class). We flag any day
where ``|1d price return| > price_thresh`` while ``|1d NAV return| < nav_thresh``
and exclude those days from summary stats — keeping them would let a single
fabricated print dominate the right tail the hypothesis lives in.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Glitch-guard thresholds (brain/32): a >20% 1-day price move with a <2% NAV move
# is an adjustment artifact, not a real discount change.
GLITCH_PRICE_RETURN_THRESH = 0.20
GLITCH_NAV_RETURN_THRESH = 0.02

# "Final window" sizes for the resolution-narrowing test (trading days).
RESOLUTION_BASELINE_LO = -250
RESOLUTION_BASELINE_HI = -60
RESOLUTION_FINAL_DAYS = 20


@dataclass(frozen=True)
class DiscountResult:
    """Per-fund discount series + glitch diagnostics (all derived, network-free)."""

    discount: pd.Series  # raw discount on every overlapping day, glitches included
    clean: pd.Series  # discount with glitch days removed (use for summary stats)
    glitch_dates: tuple[pd.Timestamp, ...]
    n_overlap: int  # overlapping price+NAV days (before glitch removal)


def compute_discount(price: pd.Series, nav: pd.Series) -> pd.Series:
    """PURE: ``discount_t = price_close_t / nav_close_t - 1`` aligned on date.

    Inner-joins the two series on their (date) index, so only days with BOTH a
    price and a NAV survive. NAV values of zero (or non-positive) are dropped —
    a zero NAV is missing/garbage, not a real -100%/divide-by-zero discount.
    Returns an empty Series (named ``discount``) when there is no overlap.
    """

    if price is None or nav is None or price.empty or nav.empty:
        return pd.Series(dtype="float64", name="discount")

    joined = pd.DataFrame({"price": price, "nav": nav}).dropna()
    joined = joined[joined["nav"] > 0]
    if joined.empty:
        return pd.Series(dtype="float64", name="discount")

    disc = (joined["price"] / joined["nav"]) - 1.0
    disc.name = "discount"
    return disc.sort_index()


def flag_glitch_days(
    price: pd.Series,
    nav: pd.Series,
    *,
    price_thresh: float = GLITCH_PRICE_RETURN_THRESH,
    nav_thresh: float = GLITCH_NAV_RETURN_THRESH,
) -> list[pd.Timestamp]:
    """PURE: dates where ``|1d price return| > price_thresh`` AND ``|1d NAV return|
    < nav_thresh`` — the BNY +224% adjustment-artifact class.

    Returns are computed on the **inner-joined** (common-date) price/NAV series so
    the two legs' 1-day changes are measured over the same calendar step (a gap on
    one side would otherwise inflate the other's "1-day" return). Returns a sorted
    list of offending timestamps (possibly empty).
    """

    if price is None or nav is None or price.empty or nav.empty:
        return []

    joined = pd.DataFrame({"price": price, "nav": nav}).dropna()
    joined = joined[joined["nav"] > 0].sort_index()
    if len(joined) < 2:
        return []

    pr = joined["price"].pct_change()
    nr = joined["nav"].pct_change()
    mask = (pr.abs() > price_thresh) & (nr.abs() < nav_thresh)
    return sorted(joined.index[mask.fillna(False)].tolist())


def discount_with_glitch_guard(
    price: pd.Series,
    nav: pd.Series,
    *,
    price_thresh: float = GLITCH_PRICE_RETURN_THRESH,
    nav_thresh: float = GLITCH_NAV_RETURN_THRESH,
) -> DiscountResult:
    """PURE: full per-fund result — raw discount, glitch dates, and a clean series.

    ``clean`` is ``discount`` with every flagged glitch day dropped; summary stats
    (mean/latest) should be read off ``clean``. ``discount`` keeps the glitch days
    so a report can show them. Returns are guarded for empty / non-overlapping
    inputs.
    """

    disc = compute_discount(price, nav)
    glitches = flag_glitch_days(
        price, nav, price_thresh=price_thresh, nav_thresh=nav_thresh
    )
    if disc.empty:
        return DiscountResult(disc, disc, tuple(glitches), 0)
    glitch_set = set(glitches)
    clean = disc[~disc.index.isin(glitch_set)]
    return DiscountResult(
        discount=disc,
        clean=clean,
        glitch_dates=tuple(glitches),
        n_overlap=len(disc),
    )


def resolution_narrowing(
    clean: pd.Series,
    *,
    baseline_lo: int = RESOLUTION_BASELINE_LO,
    baseline_hi: int = RESOLUTION_BASELINE_HI,
    final_days: int = RESOLUTION_FINAL_DAYS,
) -> tuple[float | None, float | None]:
    """PURE: the resolution-capture test for a DEAD fund's (glitch-cleaned) series.

    Returns ``(baseline_mean, final_mean)`` where ``baseline_mean`` is the mean
    discount over the window ``[len+baseline_lo : len+baseline_hi)`` (i.e. the
    -250..-60 trading-day band before the series ends) and ``final_mean`` is the
    mean over the last ``final_days`` trading days. The resolution thesis predicts
    ``final_mean`` closer to 0 than ``baseline_mean``. Either leg is ``None`` when
    there aren't enough days to populate that window (returned, never faked).
    """

    n = len(clean)
    vals = clean.to_numpy()

    lo = n + baseline_lo
    hi = n + baseline_hi
    lo = max(lo, 0)
    hi = min(hi, n)
    baseline = float(vals[lo:hi].mean()) if hi > lo else None

    final = float(vals[-final_days:].mean()) if n >= final_days else None
    return baseline, final
