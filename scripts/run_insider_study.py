#!/usr/bin/env python
"""End-to-end runner: do CLUSTERS of insider open-market buys predict returns?

Pre-registration: research/insider_cluster_preregistration.md.

Scans a pre-registered, date-stratified sample of Form-4 filing days (first N
calendar days of each month, 2019-01..2023-06), keeps every open-market purchase
(code 'P'), builds insider-buy clusters per issuer, and measures market-adjusted
CAR vs SPY over [0,+21]/[0,+63]/[0,+126]/[0,+252] trading days. Controls: a
placebo of random non-cluster dates for the same names, and a 2019-21 / 2022-23
OOS split. Writes research/insider_cluster_report.md.

Run from the worktree root:
  TRADER_SEC_USER_AGENT="name email" .venv/bin/python scripts/run_insider_study.py

Flags:
  --days-per-month N   number of leading calendar days/month to scan (default 4)
  --max-filings-per-day N   safety cap on filings parsed per day (default 0=all)
  --quick              tiny smoke sample (2020 H1, 1 day/month) for a fast check
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import edgar  # noqa: E402

from trader.catalysts.insider_clusters import (  # noqa: E402
    CAR_WINDOWS,
    PRIMARY,
    Cluster,
    EventMetrics,
    InsiderBuy,
    aggregate,
    build_clusters,
    compute_event_metrics,
    evaluate_gate,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

SINCE = date(2019, 1, 1)
UNTIL = date(2023, 6, 30)            # so 12mo forward (~to 2024-06) exists
OOS_SPLIT_YEAR = 2021               # event year <= 2021 early, else late
K_PRIMARY = 2
K_STRICT = 3
WINDOW_DAYS = 30
SEED = 12345

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "insider_cluster_report.md"

_LABELS = {
    "car_0_p21": "CAR +1m [0,+21]",
    "car_0_p63": "CAR +3m [0,+63] (PRIMARY)",
    "car_0_p126": "CAR +6m [0,+126]",
    "car_0_p252": "CAR +12m [0,+252]",
}


def _scan_days(since: date, until: date, days_per_month: int) -> list[date]:
    """First ``days_per_month`` calendar days of each month in [since, until]."""

    out: list[date] = []
    y, m = since.year, since.month
    while date(y, m, 1) <= until:
        for d in range(1, days_per_month + 1):
            try:
                day = date(y, m, d)
            except ValueError:
                continue
            if since <= day <= until:
                out.append(day)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def collect_purchases(
    scan_days: list[date], identity: str, *, max_per_day: int = 0
) -> list[InsiderBuy]:
    """Parse Form-4s on each scan day; keep every open-market purchase (code P)."""

    edgar.set_identity(identity)
    buys: list[InsiderBuy] = []
    for i, day in enumerate(scan_days):
        iso = day.isoformat()
        try:
            filings = edgar.get_filings(form="4", filing_date=f"{iso}:{iso}")
        except Exception as exc:
            log.warning("filings_list_failed", day=iso, error=str(exc))
            continue
        n_total = len(filings) if filings is not None else 0
        n_parsed = 0
        n_p = 0
        for f in filings:
            if max_per_day and n_parsed >= max_per_day:
                break
            try:
                obj = f.obj()
                df = obj.to_dataframe()
            except Exception:
                continue
            n_parsed += 1
            if df is None or len(df) == 0 or "Code" not in df.columns:
                continue
            issuer = obj.issuer
            cik = str(getattr(issuer, "cik", "") or "")
            iss_name = str(getattr(issuer, "name", "") or "")
            for _, row in df[df["Code"] == "P"].iterrows():
                tkr = str(row.get("Ticker") or "").strip()
                ins = str(row.get("Insider") or "").strip()
                td = row.get("Date")
                if not tkr or not ins or td is None or td != td:
                    continue
                try:
                    td = pd.Timestamp(td).date()
                except Exception:
                    continue
                shares = float(row.get("Shares") or 0.0)
                try:
                    price = float(row.get("Price") or 0.0)
                except Exception:
                    price = 0.0
                buys.append(
                    InsiderBuy(
                        cik=cik or tkr, ticker=tkr, issuer=iss_name or tkr,
                        insider=ins, trade_date=td, shares=shares, price=price,
                    )
                )
                n_p += 1
        log.info(
            "scan_day_done", day=iso, idx=i + 1, of=len(scan_days),
            filings=n_total, parsed=n_parsed, p_rows=n_p, buys_total=len(buys),
        )
    return buys


def _placebo_date(close: pd.Series, real_dates: set[date], rng: random.Random) -> date | None:
    """A random trading date for this name, >= 30 trading days away from any real
    cluster, that leaves a full forward window. None if none qualifies."""

    idx = pd.DatetimeIndex(close.dropna().sort_index().index)
    need_hi = max(w[1] for w in CAR_WINDOWS.values())
    if len(idx) < need_hi + 40:
        return None
    real_pos = [int(idx.searchsorted(pd.Timestamp(d))) for d in real_dates]
    candidates = []
    for pos in range(20, len(idx) - need_hi - 1):
        if all(abs(pos - rp) > 30 for rp in real_pos):
            candidates.append(pos)
    if not candidates:
        return None
    return idx[rng.choice(candidates)].date()


def _metrics_for_clusters(
    clusters: list[Cluster], spy_close: pd.Series, *, placebo: bool, seed: int,
) -> tuple[list[EventMetrics], dict[str, int]]:
    """Fetch prices per issuer and compute CARs. Real or placebo events."""

    rng = random.Random(seed)
    # group clusters by ticker so we fetch each name once
    by_ticker: dict[str, list[Cluster]] = {}
    for c in clusters:
        by_ticker.setdefault(c.ticker, []).append(c)

    out: list[EventMetrics] = []
    counts = {"no_price": 0, "no_window": 0, "no_placebo": 0, "ok": 0}
    names = sorted(by_ticker)
    for i, tkr in enumerate(names):
        if i % 25 == 0:
            log.info("price_progress", done=i, of=len(names), ok=len(out), placebo=placebo)
        cs = by_ticker[tkr]
        lo = min(c.event_date for c in cs) - timedelta(days=120)
        hi = max(c.event_date for c in cs) + timedelta(days=430)
        px = fetch_daily(tkr, lo, hi)
        if px is None:
            counts["no_price"] += len(cs)
            continue
        close, _vol = px
        real_dates = {c.event_date for c in cs}
        for c in cs:
            if placebo:
                pd_date = _placebo_date(close, real_dates, rng)
                if pd_date is None:
                    counts["no_placebo"] += 1
                    continue
                m = compute_event_metrics(close, spy_close, c, event_date=pd_date)
            else:
                m = compute_event_metrics(close, spy_close, c)
            if m is None:
                counts["no_window"] += 1
                continue
            out.append(m)
            counts["ok"] += 1
    return out, counts


def _table(result) -> str:
    rows = ["| window | n | mean % | median % | % pos | t-stat |", "|---|---|---|---|---|---|"]
    for k in ("car_0_p21", "car_0_p63", "car_0_p126", "car_0_p252"):
        w = result.stats[k]
        rows.append(
            f"| {_LABELS[k]} | {w.n} | {w.mean * 100:+.2f} | {w.median * 100:+.2f} | "
            f"{w.pct_positive:.0%} | {w.t_stat:+.2f} |"
        )
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-per-month", type=int, default=4)
    ap.add_argument("--max-filings-per-day", type=int, default=0)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    identity = os.getenv("TRADER_SEC_USER_AGENT")
    if not identity:
        print("ERROR: set TRADER_SEC_USER_AGENT", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    since, until, dpm = SINCE, UNTIL, args.days_per_month
    if args.quick:
        since, until, dpm = date(2020, 1, 1), date(2020, 6, 30), 1

    scan_days = _scan_days(since, until, dpm)
    log.info("scan_plan", since=str(since), until=str(until), days_per_month=dpm, n_days=len(scan_days))

    buys = collect_purchases(scan_days, identity, max_per_day=args.max_filings_per_day)
    pd.DataFrame([b.__dict__ for b in buys]).to_csv(OUT_DIR / "insider_buys.csv", index=False)
    log.info("purchases_collected", n_buys=len(buys))

    clusters = build_clusters(buys, k_distinct=K_PRIMARY, window_days=WINDOW_DAYS)
    clusters_k3 = build_clusters(buys, k_distinct=K_STRICT, window_days=WINDOW_DAYS)
    pd.DataFrame([c.__dict__ for c in clusters]).to_csv(OUT_DIR / "insider_clusters.csv", index=False)
    log.info("clusters_detected", k2=len(clusters), k3=len(clusters_k3))

    spy = fetch_daily("SPY", since - timedelta(days=200), until + timedelta(days=460))
    if spy is None:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 3
    spy_close, _ = spy

    real, real_counts = _metrics_for_clusters(clusters, spy_close, placebo=False, seed=SEED)
    placebo, pl_counts = _metrics_for_clusters(clusters, spy_close, placebo=True, seed=SEED)
    k3_real, k3_counts = _metrics_for_clusters(clusters_k3, spy_close, placebo=False, seed=SEED)
    log.info("metrics_done", real=len(real), placebo=len(placebo), k3=len(k3_real))

    early = [m for m in real if m.event_date.year <= OOS_SPLIT_YEAR]
    late = [m for m in real if m.event_date.year > OOS_SPLIT_YEAR]
    res_real = aggregate(real, label="real")
    res_placebo = aggregate(placebo, label="placebo")
    res_early = aggregate(early, label=f"oos<= {OOS_SPLIT_YEAR}")
    res_late = aggregate(late, label=f"oos> {OOS_SPLIT_YEAR}")
    res_k3 = aggregate(k3_real, label="k3")
    verdict = evaluate_gate(res_real, res_placebo, res_early, res_late)

    n_issuers = len({c.cik for c in clusters})
    lines = [
        "# Insider-Buy Clusters as a Forward-Return Signal — Event Study Result",
        "",
        "Pre-registration: `research/insider_cluster_preregistration.md`.",
        "Market-adjusted CAR = stock return minus SPY (beta=1), summed over the",
        "trading-day window from the event date (the LAST buy in the cluster).",
        "",
        "## Run metadata",
        f"- Form-4 scan: first {dpm} calendar day(s)/month, {since} .. {until}",
        f"- Scanned filing-days: {len(scan_days)}",
        f"- Cluster def: >= K distinct insiders within {WINDOW_DAYS} calendar days; K_primary={K_PRIMARY}, K_strict={K_STRICT}",
        f"- Benchmark: SPY | OOS split: event year <= {OOS_SPLIT_YEAR} (early) vs > (late)",
        f"- Placebo: random non-cluster dates for the same names (seed={SEED})",
        "",
        "## Sample accounting (count the dropouts honestly)",
        f"- Open-market purchases (code P) collected: {len(buys)}",
        f"- K>=2 clusters detected: {len(clusters)}  (distinct issuers: {n_issuers})",
        f"- K>=3 clusters detected: {len(clusters_k3)}",
        f"- K>=2 events with full [0,+252] price window (study N): {len(real)}",
        f"  - dropped, no yfinance price (delisted/unmatched ticker): {real_counts['no_price']}",
        f"  - dropped, short/incomplete forward window: {real_counts['no_window']}",
        f"- Placebo events built: {len(placebo)}  (no placebo slot: {pl_counts['no_placebo']})",
        f"- OOS early (<= {OOS_SPLIT_YEAR}): {len(early)}  | OOS late: {len(late)}",
        f"- K>=3 study N: {len(k3_real)} (no price: {k3_counts['no_price']}, short: {k3_counts['no_window']})",
        "",
        "> yfinance purges delisted tickers, so the `no price` count is a real,",
        "> survivorship-biased dropout: the survivors that remain are tilted UP.",
        "",
        "## Market-adjusted CAR vs SPY — K>=2 clusters (REAL)",
        _table(res_real),
        "",
        "## Placebo (random non-cluster dates, same names)",
        _table(res_placebo),
        "",
        f"## OOS early (<= {OOS_SPLIT_YEAR})",
        _table(res_early),
        "",
        f"## OOS late (> {OOS_SPLIT_YEAR})",
        _table(res_late),
        "",
        "## Robustness: K>=3 clusters (stricter conviction)",
        _table(res_k3),
        "",
        "## Pre-registered gate verdict",
        "",
        f"### {'PASS' if verdict.passed else 'FAIL (idea killed / null)'}",
        "",
    ]
    lines += [f"- {r}" for r in verdict.reasons]
    lines += [
        "",
        "## How to read this",
        "",
        f"Primary horizon is `{PRIMARY}` (~3 months). A real, tradeable cluster",
        "signal needs: N>=30, a positive primary CAR with |t|>=2, that BEATS the",
        "same-names placebo, and keeps its sign across the OOS split. Anything",
        "less is consistent with the honest prior: the cluster-buy effect is the",
        "best-documented insider signal but is old, public, and likely decayed.",
        "Even a nominal 'pass' here would still owe a cluster-robust standard",
        "error (events on correlated small-caps are not independent) before any",
        "capital — we did NOT correct for cross-sectional correlation.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nReport: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
