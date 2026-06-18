"""Daily option-derived features from the QQQ raw-quote lake.

The lake stores raw bid/ask quotes (no greeks), so features are computed directly
from option PRICES at the end-of-day snapshot — cleaner than BS inversion:

* ``atm_vol``    — ATM straddle premium / spot at ~21 DTE (implied-move proxy).
* ``put_skew``   — (5%-OTM put mid - 5%-OTM call mid) / spot (downside-skew proxy).
* ``term_slope`` — far straddle% (~45 DTE) minus near straddle% (~21 DTE).

These are differentiated inputs (most retail miners lack options data), fed into
the same deflated-Sharpe + OOS lab so any "signal" is multiple-testing-corrected.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import structlog

from trader.config import intraday_lake_root

log = structlog.get_logger()
# Override via TRADER_LAKE_ROOT; repo-relative default. The 1-min lake is
# licensed (ThetaData-derived) and not shipped — see trader.config.
DEFAULT_LAKE = str(intraday_lake_root())


def _straddle_pct(eod: pd.DataFrame, spot: float, target_dte: int) -> float | None:
    """ATM straddle premium / spot for the expiration nearest ``target_dte``."""
    if eod.empty:
        return None
    exp = eod.iloc[(eod["dte"] - target_dte).abs().argsort()].iloc[0]["exp"]
    e = eod[eod["exp"] == exp]
    katm = e.iloc[(e["strike"] - spot).abs().argsort()].iloc[0]["strike"]
    c = e[(e["strike"] == katm) & (e["call_put"] == "Call")]["mid"]
    p = e[(e["strike"] == katm) & (e["call_put"] == "Put")]["mid"]
    if c.empty or p.empty or spot <= 0:
        return None
    return float(c.iloc[0] + p.iloc[0]) / spot


def _put_skew(eod: pd.DataFrame, spot: float, target_dte: int = 21, otm: float = 0.05) -> float | None:
    sub = eod[(eod["dte"] >= 5) & (eod["dte"] <= 45)]
    if sub.empty:
        return None
    exp = sub.iloc[(sub["dte"] - target_dte).abs().argsort()].iloc[0]["exp"]
    e = eod[eod["exp"] == exp]
    put_k = spot * (1 - otm)
    call_k = spot * (1 + otm)
    pset = e[e["call_put"] == "Put"]
    cset = e[e["call_put"] == "Call"]
    if pset.empty or cset.empty:
        return None
    put_mid = pset.iloc[(pset["strike"] - put_k).abs().argsort()].iloc[0]["mid"]
    call_mid = cset.iloc[(cset["strike"] - call_k).abs().argsort()].iloc[0]["mid"]
    return float(put_mid - call_mid) / spot if spot > 0 else None


def day_features(con, trade_date: str, lake: str = DEFAULT_LAKE) -> dict | None:
    day = f"read_parquet('{lake}/trade_date={trade_date}/*.parquet')"
    try:
        df = con.execute(
            f"select cast(expiration as date) exp, strike, call_put, "
            f"(bid+ask)/2.0 mid, underlying_price ul from {day} "
            f"where quote_ts = (select max(quote_ts) from {day}) "
            f"and bid is not null and ask is not null and bid > 0"
        ).df()
    except Exception as exc:  # best effort per day
        log.warning("opt_feat_day_failed", date=trade_date, error=str(exc))
        return None
    if df.empty or df["ul"].max() <= 0:
        return None
    spot = float(df["ul"].max())
    td = pd.Timestamp(trade_date)
    df["dte"] = (pd.to_datetime(df["exp"]) - td).dt.days
    near = _straddle_pct(df[(df["dte"] >= 5) & (df["dte"] <= 45)], spot, 21)
    far = _straddle_pct(df[(df["dte"] >= 25) & (df["dte"] <= 75)], spot, 45)
    return {
        "trade_date": trade_date,
        "spot": spot,
        "atm_vol": near,
        "put_skew": _put_skew(df, spot),
        "term_slope": (far - near) if (near is not None and far is not None) else None,
    }


def extract_features(since: date, until: date, *, lake: str = DEFAULT_LAKE) -> pd.DataFrame:
    """Extract daily option features for all populated trade-dates in the window."""
    import duckdb

    con = duckdb.connect()
    dates = [
        r[0] for r in con.execute(
            f"select distinct trade_date from read_parquet('{lake}/**/*.parquet', hive_partitioning=1) "
            f"where trade_date >= '{since}' and trade_date <= '{until}' order by trade_date"
        ).fetchall()
    ]
    rows = []
    for i, d in enumerate(dates):
        f = day_features(con, str(d), lake)
        if f is not None:
            rows.append(f)
        if i % 100 == 0:
            log.info("opt_feat_progress", done=i, total=len(dates), kept=len(rows))
    out = pd.DataFrame(rows)
    if not out.empty:
        out["trade_date"] = pd.to_datetime(out["trade_date"])
        out = out.set_index("trade_date").sort_index()
    return out
