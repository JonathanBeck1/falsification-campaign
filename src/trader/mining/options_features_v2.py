"""Daily v2 option-derived features from the QQQ raw-quote lake.

The v2 set adds price, displayed-depth, term-structure, and microstructure
proxies computed from each end-of-day option-chain snapshot.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import structlog

from trader.config import intraday_lake_root

# Override via TRADER_LAKE_ROOT; repo-relative default (lake not shipped).
DEFAULT_LAKE = str(intraday_lake_root())
log = structlog.get_logger()


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


def compute_v2_features(df: pd.DataFrame, spot: float, trade_date: str) -> dict[str, float | None]:
    """Compute v2 features from one end-of-day option-chain snapshot."""
    out: dict[str, float | None] = {
        "trade_date": trade_date,  # type: ignore[dict-item]
        "spot": spot,
    }

    try:
        sub = df[(df["dte"] >= 15) & (df["dte"] <= 30)]
        if sub.empty or spot <= 0:
            out["gex_depth_proxy"] = None
        else:
            weights = (sub["strike"] / spot - 1.0) ** 2
            out["gex_depth_proxy"] = float((weights * (sub["bid_size"] + sub["ask_size"])).sum())
    except Exception as exc:
        log.warning("opt_feat_v2_failed", date=trade_date, feature="gex_depth_proxy", error=str(exc))
        out["gex_depth_proxy"] = None

    try:
        sub = df[(df["dte"] >= 5) & (df["dte"] <= 45)]
        if sub.empty or spot <= 0:
            out["skew_25d"] = None
        else:
            exp = sub.iloc[(sub["dte"] - 21).abs().argsort()].iloc[0]["exp"]
            e = sub[sub["exp"] == exp]
            pset = e[e["call_put"] == "Put"]
            cset = e[e["call_put"] == "Call"]
            if pset.empty or cset.empty:
                out["skew_25d"] = None
            else:
                put_mid = pset.iloc[(pset["strike"] - spot * 0.92).abs().argsort()].iloc[0]["mid"]
                call_mid = cset.iloc[(cset["strike"] - spot * 1.08).abs().argsort()].iloc[0]["mid"]
                out["skew_25d"] = float(put_mid - call_mid) / spot
    except Exception as exc:
        log.warning("opt_feat_v2_failed", date=trade_date, feature="skew_25d", error=str(exc))
        out["skew_25d"] = None

    try:
        sub = df[(df["dte"] >= 15) & (df["dte"] <= 30)]
        psum = float((sub.loc[sub["call_put"] == "Put", "bid_size"] + sub.loc[sub["call_put"] == "Put", "ask_size"]).sum())
        csum = float(
            (sub.loc[sub["call_put"] == "Call", "bid_size"] + sub.loc[sub["call_put"] == "Call", "ask_size"]).sum()
        )
        out["pc_size_ratio"] = psum / csum if csum > 0 else None
    except Exception as exc:
        log.warning("opt_feat_v2_failed", date=trade_date, feature="pc_size_ratio", error=str(exc))
        out["pc_size_ratio"] = None

    try:
        near = _straddle_pct(df[(df["dte"] >= 3) & (df["dte"] <= 14)], spot, 7)
        middle = _straddle_pct(df[(df["dte"] >= 15) & (df["dte"] <= 45)], spot, 30)
        far = _straddle_pct(df[(df["dte"] >= 40) & (df["dte"] <= 75)], spot, 60)
        out["term_curvature"] = (
            2.0 * middle - near - far if near is not None and middle is not None and far is not None else None
        )
    except Exception as exc:
        log.warning("opt_feat_v2_failed", date=trade_date, feature="term_curvature", error=str(exc))
        out["term_curvature"] = None

    try:
        sub = df[
            (df["dte"] >= 15)
            & (df["dte"] <= 30)
            & ((df["strike"] - spot).abs() <= 0.02 * spot)
            & (df["bid"] > 0)
            & (df["ask"] > 0)
        ]
        if sub.empty:
            out["avg_spread_pct"] = None
        else:
            spread_pct = (sub["ask"] - sub["bid"]) / ((sub["ask"] + sub["bid"]) / 2.0)
            out["avg_spread_pct"] = float(spread_pct.mean())
    except Exception as exc:
        log.warning("opt_feat_v2_failed", date=trade_date, feature="avg_spread_pct", error=str(exc))
        out["avg_spread_pct"] = None

    try:
        sub = df[
            (df["dte"] >= 15)
            & (df["dte"] <= 30)
            & ((df["strike"] - spot).abs() <= 0.02 * spot)
        ]
        bsum = float(sub["bid_size"].sum())
        asum = float(sub["ask_size"].sum())
        out["depth_imbalance"] = (bsum - asum) / (bsum + asum) if bsum + asum > 0 else None
    except Exception as exc:
        log.warning("opt_feat_v2_failed", date=trade_date, feature="depth_imbalance", error=str(exc))
        out["depth_imbalance"] = None

    return out


def day_features_v2(con, trade_date: str, lake: str = DEFAULT_LAKE) -> dict | None:
    """Load and compute v2 features for one populated trade date."""
    day = f"read_parquet('{lake}/trade_date={trade_date}/*.parquet')"
    try:
        df = con.execute(
            f"select cast(expiration as date) exp, strike, call_put, "
            f"(bid+ask)/2.0 mid, bid, ask, bid_size, ask_size, underlying_price ul from {day} "
            f"where quote_ts = (select max(quote_ts) from {day}) "
            f"and bid is not null and ask is not null and bid > 0"
        ).df()
    except Exception as exc:
        log.warning("opt_feat_v2_day_failed", date=trade_date, error=str(exc))
        return None
    if df.empty or df["ul"].max() <= 0:
        return None
    spot = float(df["ul"].max())
    df["dte"] = (pd.to_datetime(df["exp"]) - pd.Timestamp(trade_date)).dt.days
    return compute_v2_features(df, spot, trade_date)


def extract_features_v2(
    since: date,
    until: date,
    *,
    lake: str = DEFAULT_LAKE,
    base_features_path: str | Path | None = None,
) -> pd.DataFrame:
    """Extract daily v2 option features for all populated trade dates."""
    import duckdb

    con = duckdb.connect()
    try:
        dates = [
            r[0]
            for r in con.execute(
                f"select distinct trade_date from read_parquet('{lake}/**/*.parquet', hive_partitioning=1) "
                f"where trade_date >= '{since}' and trade_date <= '{until}' order by trade_date"
            ).fetchall()
        ]
    except Exception as exc:
        log.warning("opt_feat_v2_dates_failed", since=str(since), until=str(until), error=str(exc))
        dates = []

    rows = []
    for i, day in enumerate(dates):
        features = day_features_v2(con, str(day), lake)
        if features is not None:
            rows.append(features)
        if i % 100 == 0:
            log.info("opt_feat_v2_progress", done=i, total=len(dates), kept=len(rows))
    con.close()

    out = pd.DataFrame(rows)
    if not out.empty:
        out["trade_date"] = pd.to_datetime(out["trade_date"])
        out = out.set_index("trade_date").sort_index()

    base_path = Path(base_features_path) if base_features_path is not None else None
    if base_path is not None and base_path.exists():
        try:
            base = pd.read_parquet(base_path)
            if "trade_date" in base.columns:
                base["trade_date"] = pd.to_datetime(base["trade_date"])
                base = base.set_index("trade_date")
            else:
                base.index = pd.to_datetime(base.index)
            out = out.join(base[["atm_vol"]], how="left")
            out["vol_of_vol_20"] = out["atm_vol"].rolling(20).std(ddof=0)
            out = out.drop(columns="atm_vol")
        except Exception as exc:
            log.warning("opt_feat_v2_base_failed", path=str(base_path), error=str(exc))
            out["vol_of_vol_20"] = float("nan")
    else:
        out["vol_of_vol_20"] = float("nan")
    return out
