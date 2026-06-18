#!/usr/bin/env python
"""T44 — Insider Cluster Buying: end-to-end event study (free data only).

Pre-registration: research/insider_clusters_preregistration.md.

Scans the FROZEN stratified grid of Form-4 filing-days (1st/8th/15th/22nd of
Jan/Mar/May/Jul/Sep/Nov, 2016..2023), keeps every open-market purchase (code
'P'), builds insider-buy clusters per issuer (>= K distinct insiders within 30
calendar days), and measures market-adjusted CAR vs SPY over
[0,+21]/[0,+63]/[0,+126]/[0,+252] trading days. Applies a 40 bps round-trip
cost; the AFTER-COST primary CAR is the only ranked metric. Controls: a
same-names non-event placebo and a <=2020 / >=2021 OOS split (both halves must
be N>=10). Robustness: drop the top-5 contributors. Writes
data/insider_clusters_results.txt.

Fast collector: derive the full-submission ``.txt`` URL from (CIK, accession)
in the EDGAR Form-4 index and parse the embedded ownership XML directly — one
HTTP round trip per filing, throttled to stay within SEC fair-access limits.

Run from the worktree root:
  TRADER_SEC_USER_AGENT="name email" .venv/bin/python \
      scripts/run_insider_clusters_study.py

Flags:
  --quick            tiny smoke sample (2020, two scan days) for a fast check
  --max-workers N    concurrent submission fetches (default 8)
  --limit-days N     cap scanned filing-days (debug); 0 = all (default 0)
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import os
import random
import re
import sys
import threading
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import edgar  # noqa: E402

from trader.catalysts.insider_clusters import (  # noqa: E402
    CAR_WINDOWS,
    PRIMARY,
    Cluster,
    EventMetrics,
    InsiderBuy,
    after_cost_metrics,
    aggregate,
    build_clusters,
    compute_event_metrics,
    drop_top_contributors,
    evaluate_gate,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

# Frozen pre-registered grid.
SINCE_YEAR, UNTIL_YEAR = 2016, 2023
SCAN_MONTHS = (1, 3, 5, 7, 9, 11)
SCAN_DAYS_OF_MONTH = (1, 8, 15, 22)
UNTIL = date(2023, 6, 30)            # 12mo forward (~to 2024-06) exists
OOS_SPLIT_YEAR = 2020               # event year <= 2020 early, >= 2021 late
K_PRIMARY = 2
K_STRICT = 3
WINDOW_DAYS = 30
ROUND_TRIP = 0.0040                 # 40 bps after-cost adjustment (pre-reg)
SEED = 12345

OUT_DIR = ROOT / "output" / "catalysts"
RESULTS_PATH = ROOT / "data" / "insider_clusters_results.txt"

_LABELS = {
    "car_0_p21": "CAR +1m [0,+21]",
    "car_0_p63": "CAR +3m [0,+63] (PRIMARY)",
    "car_0_p126": "CAR +6m [0,+126]",
    "car_0_p252": "CAR +12m [0,+252]",
}

_UA = os.getenv("TRADER_SEC_USER_AGENT", "")
_HDRS = {"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"}
_XML_RE = re.compile(rb"<XML>\s*(.*?)\s*</XML>", re.S)
# crude rate limiter shared across worker threads (SEC fair-access ~10 req/s)
_RATE_LOCK = threading.Lock()
_LAST_REQ = [0.0]
_MIN_INTERVAL = 0.11  # ~9 req/s aggregate


def scan_days() -> list[date]:
    """The frozen stratified grid of filing-days to scan."""

    out: list[date] = []
    for y in range(SINCE_YEAR, UNTIL_YEAR + 1):
        for m in SCAN_MONTHS:
            for d in SCAN_DAYS_OF_MONTH:
                try:
                    day = date(y, m, d)
                except ValueError:
                    continue
                if date(2016, 1, 1) <= day <= UNTIL:
                    out.append(day)
    return out


def _sub_url(cik: int | str, acc: str) -> str:
    nod = acc.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nod}/{acc}.txt"


def _throttle() -> None:
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.time() - _LAST_REQ[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQ[0] = time.time()


def _parse_submission(data: bytes) -> list[tuple]:
    """Parse the embedded ownership XML; return (owner, cik, ticker, date,
    shares, price) for every non-derivative code-P transaction."""

    m = _XML_RE.search(data)
    if not m:
        return []
    try:
        root = etree.fromstring(m.group(1).strip())
    except Exception:
        return []
    if not str(root.tag).endswith("ownershipDocument"):
        return []
    cik = root.findtext(".//issuer/issuerCik")
    sym = root.findtext(".//issuer/issuerTradingSymbol")
    name = root.findtext(".//issuer/issuerName")
    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName")
    out: list[tuple] = []
    for t in root.findall(".//nonDerivativeTransaction"):
        if t.findtext(".//transactionCoding/transactionCode") != "P":
            continue
        out.append(
            (
                owner,
                cik,
                sym,
                name,
                t.findtext(".//transactionDate/value"),
                t.findtext(".//transactionShares/value"),
                t.findtext(".//transactionPricePerShare/value"),
            )
        )
    return out


def _fetch_one(row) -> list[InsiderBuy]:
    url = _sub_url(row.cik, row.accession_number)
    _throttle()
    try:
        req = urllib.request.Request(url, headers=_HDRS)
        resp = urllib.request.urlopen(req, timeout=30)
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    except Exception:
        return []
    buys: list[InsiderBuy] = []
    for owner, cik, sym, name, td, sh, pr in _parse_submission(raw):
        tkr = str(sym or "").strip().upper()
        ins = str(owner or "").strip()
        if not tkr or not ins or not td:
            continue
        try:
            tdate = pd.Timestamp(td).date()
        except Exception:
            continue
        try:
            shares = float(sh or 0.0)
        except Exception:
            shares = 0.0
        try:
            price = float(pr or 0.0)
        except Exception:
            price = 0.0
        buys.append(
            InsiderBuy(
                cik=str(cik or tkr),
                ticker=tkr,
                issuer=str(name or tkr),
                insider=ins,
                trade_date=tdate,
                shares=shares,
                price=price,
            )
        )
    return buys


CHECKPOINT_CSV = OUT_DIR / "insider_clusters_buys.csv"


def _load_checkpoint() -> tuple[list[InsiderBuy], set[str]]:
    """Load previously collected buys + the set of scan-days already done.

    The checkpoint CSV is appended one scan-day at a time so a killed process
    can resume without re-fetching days already on disk. Empty/holiday days are
    recorded too (via a sentinel row) so they are not re-scanned.
    """

    if not CHECKPOINT_CSV.exists():
        return [], set()
    df = pd.read_csv(CHECKPOINT_CSV, dtype={"cik": str})
    if "scan_day" not in df.columns:
        return [], set()  # legacy/smoke CSV without checkpoint column -> ignore
    done = {str(d) for d in df["scan_day"].dropna().unique()}
    buys: list[InsiderBuy] = []
    for r in df.itertuples():
        if not getattr(r, "ticker", "") or r.ticker != r.ticker:
            continue  # sentinel row for an empty scan-day
        try:
            buys.append(
                InsiderBuy(
                    cik=str(r.cik), ticker=str(r.ticker), issuer=str(r.issuer),
                    insider=str(r.insider),
                    trade_date=pd.Timestamp(r.trade_date).date(),
                    shares=float(r.shares), price=float(r.price),
                )
            )
        except Exception:
            continue
    return buys, done


def _append_checkpoint(day: date, day_buys: list[InsiderBuy]) -> None:
    iso = day.isoformat()
    if day_buys:
        rows = [{**b.__dict__, "scan_day": iso} for b in day_buys]
    else:
        rows = [{  # sentinel so an empty/holiday day is not re-scanned
            "cik": "", "ticker": float("nan"), "issuer": "", "insider": "",
            "trade_date": "", "shares": 0.0, "price": 0.0, "scan_day": iso,
        }]
    df = pd.DataFrame(rows)
    header = not CHECKPOINT_CSV.exists()
    df.to_csv(CHECKPOINT_CSV, mode="a", header=header, index=False)


def collect_purchases(days: list[date], *, max_workers: int) -> list[InsiderBuy]:
    edgar.set_identity(_UA)
    buys, done = _load_checkpoint()
    if done:
        log.info("checkpoint_loaded", days_done=len(done), buys_loaded=len(buys))
    for i, day in enumerate(days):
        iso = day.isoformat()
        if iso in done:
            continue  # already collected in a prior (possibly killed) run
        try:
            df = edgar.get_filings(form="4", filing_date=f"{iso}:{iso}").to_pandas()
        except Exception as exc:
            log.warning("filings_list_failed", day=iso, error=str(exc))
            continue
        rows = list(df.itertuples()) if df is not None else []
        day_buys: list[InsiderBuy] = []
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            for res in ex.map(_fetch_one, rows):
                day_buys.extend(res)
        _append_checkpoint(day, day_buys)  # persist BEFORE extending in-memory
        buys.extend(day_buys)
        log.info(
            "scan_day_done", day=iso, idx=i + 1, of=len(days),
            filings=len(rows), p_buys=len(day_buys), buys_total=len(buys),
        )
    return buys


def _placebo_date(close: pd.Series, real_dates: set[date], rng: random.Random) -> date | None:
    idx = pd.DatetimeIndex(close.dropna().sort_index().index)
    need_hi = max(w[1] for w in CAR_WINDOWS.values())
    if len(idx) < need_hi + 40:
        return None
    real_pos = [int(idx.searchsorted(pd.Timestamp(d))) for d in real_dates]
    candidates = [
        pos for pos in range(20, len(idx) - need_hi - 1)
        if all(abs(pos - rp) > 30 for rp in real_pos)
    ]
    if not candidates:
        return None
    return idx[rng.choice(candidates)].date()


def metrics_for_clusters(
    clusters: list[Cluster], spy_close: pd.Series, *, placebo: bool, seed: int,
) -> tuple[list[EventMetrics], dict[str, int]]:
    rng = random.Random(seed)
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
                pdte = _placebo_date(close, real_dates, rng)
                if pdte is None:
                    counts["no_placebo"] += 1
                    continue
                m = compute_event_metrics(close, spy_close, c, event_date=pdte)
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
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--limit-days", type=int, default=0)
    ap.add_argument(
        "--target-days", type=int, default=0,
        help="evenly subsample the frozen grid to ~N trading-days spanning the "
             "whole 2016-2023 period (deterministic stride; preserves OOS span)",
    )
    args = ap.parse_args()

    if not _UA:
        print("ERROR: set TRADER_SEC_USER_AGENT='descriptive name email'", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    days = [d for d in scan_days() if d.weekday() < 5]  # only trading weekdays
    if args.target_days and 0 < args.target_days < len(days):
        # deterministic even stride so coverage spans the full period (keeps OOS)
        stride = len(days) / args.target_days
        idx = sorted({int(i * stride) for i in range(args.target_days)})
        days = [days[j] for j in idx if j < len(days)]
    if args.quick:
        days = [date(2020, 3, 2), date(2020, 9, 1)]
    if args.limit_days:
        days = days[: args.limit_days]
    log.info("scan_plan", n_days=len(days), first=str(days[0]), last=str(days[-1]))

    t0 = time.time()
    # collect_purchases checkpoints each scan-day to CHECKPOINT_CSV as it goes
    # (resumable across a killed process); no end-of-run overwrite needed.
    buys = collect_purchases(days, max_workers=args.max_workers)
    log.info("purchases_collected", n_buys=len(buys), secs=round(time.time() - t0, 1))

    clusters = build_clusters(buys, k_distinct=K_PRIMARY, window_days=WINDOW_DAYS)
    clusters_k3 = build_clusters(buys, k_distinct=K_STRICT, window_days=WINDOW_DAYS)
    pd.DataFrame([c.__dict__ for c in clusters]).to_csv(
        OUT_DIR / "insider_clusters_clusters.csv", index=False
    )
    n_issuers = len({c.cik for c in clusters})
    log.info("clusters_detected", k2=len(clusters), k3=len(clusters_k3), issuers=n_issuers)

    spy = fetch_daily("SPY", date(2015, 9, 1), date(2024, 10, 1))
    if spy is None:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 3
    spy_close, _ = spy

    real, real_counts = metrics_for_clusters(clusters, spy_close, placebo=False, seed=SEED)
    placebo, pl_counts = metrics_for_clusters(clusters, spy_close, placebo=True, seed=SEED)
    k3_real, k3_counts = metrics_for_clusters(clusters_k3, spy_close, placebo=False, seed=SEED)
    log.info("metrics_done", real=len(real), placebo=len(placebo), k3=len(k3_real))

    # AFTER-COST is the ranked metric.
    real_ac = after_cost_metrics(real, round_trip=ROUND_TRIP)
    placebo_ac = after_cost_metrics(placebo, round_trip=ROUND_TRIP)
    k3_ac = after_cost_metrics(k3_real, round_trip=ROUND_TRIP)

    early = [m for m in real_ac if m.event_date.year <= OOS_SPLIT_YEAR]
    late = [m for m in real_ac if m.event_date.year > OOS_SPLIT_YEAR]

    res_real_gross = aggregate(real, label="real_gross")
    res_real = aggregate(real_ac, label="real_after_cost")
    res_placebo = aggregate(placebo_ac, label="placebo_after_cost")
    res_early = aggregate(early, label=f"oos<= {OOS_SPLIT_YEAR}")
    res_late = aggregate(late, label=f"oos> {OOS_SPLIT_YEAR}")
    res_k3 = aggregate(k3_ac, label="k3_after_cost")

    verdict = evaluate_gate(res_real, res_placebo, res_early, res_late)

    # Concentration robustness: drop top-5 contributors (after cost).
    trimmed = drop_top_contributors(real_ac, k=5)
    res_trimmed = aggregate(trimmed, label="real_after_cost_drop_top5")

    lines = [
        "# T44 — Insider Cluster Buying — Event Study Result (after-cost)",
        "",
        "Pre-registration: research/insider_clusters_preregistration.md",
        "Market-adjusted CAR = stock ret - SPY (beta=1), summed over the window;",
        f"AFTER-COST subtracts a {ROUND_TRIP * 1e4:.0f} bps round trip per event.",
        "",
        "## Run metadata",
        f"- Frozen grid: days {SCAN_DAYS_OF_MONTH} of months {SCAN_MONTHS}, "
        f"{SINCE_YEAR}..{UNTIL_YEAR} (<= {UNTIL})",
        f"- Scanned filing-days: {len(days)}",
        f"- Cluster def: >= K distinct insiders within {WINDOW_DAYS} calendar days; "
        f"K_primary={K_PRIMARY}, K_strict={K_STRICT}",
        f"- Benchmark: SPY | OOS split: event year <= {OOS_SPLIT_YEAR} vs >= {OOS_SPLIT_YEAR + 1}",
        f"- Placebo: random non-cluster dates, same names (seed={SEED})",
        f"- After-cost round trip: {ROUND_TRIP * 1e4:.0f} bps",
        "",
        "## Sample accounting (dropouts counted honestly)",
        f"- Open-market purchases (code P) collected: {len(buys)}",
        f"- K>=2 clusters detected: {len(clusters)}  (distinct issuers: {n_issuers})",
        f"- K>=3 clusters detected: {len(clusters_k3)}",
        f"- K>=2 events with full [0,+252] window (study N): {len(real)}",
        f"  - dropped, no yfinance price (delisted/unmatched): {real_counts['no_price']}",
        f"  - dropped, short/incomplete forward window: {real_counts['no_window']}",
        f"- Placebo events built: {len(placebo)}  (no placebo slot: {pl_counts['no_placebo']})",
        f"- OOS early (<= {OOS_SPLIT_YEAR}): {len(early)}  | OOS late: {len(late)}",
        f"- K>=3 study N: {len(k3_real)} (no price: {k3_counts['no_price']}, "
        f"short: {k3_counts['no_window']})",
        "",
        "> yfinance purges delisted tickers, so `no price` is a real,",
        "> survivorship-biased dropout: the survivors that remain tilt UP.",
        "",
        "## K>=2 clusters — GROSS (context only, not ranked)",
        _table(res_real_gross),
        "",
        "## K>=2 clusters — AFTER-COST (RANKED)",
        _table(res_real),
        "",
        "## Placebo (same names, non-event dates) — after-cost",
        _table(res_placebo),
        "",
        f"## OOS early (<= {OOS_SPLIT_YEAR}) — after-cost",
        _table(res_early),
        "",
        f"## OOS late (>= {OOS_SPLIT_YEAR + 1}) — after-cost",
        _table(res_late),
        "",
        "## Concentration robustness — after-cost, top-5 contributors dropped",
        _table(res_trimmed),
        "",
        "## Robustness: K>=3 clusters (stricter conviction) — after-cost",
        _table(res_k3),
        "",
        "## Pre-registered gate verdict",
        "",
        f"### {'PASS' if verdict.passed else 'FAIL (idea killed / null)'}",
        "",
    ]
    lines += [f"- {r}" for r in verdict.reasons]
    primary_gross = res_real_gross.stats[PRIMARY]
    primary_ac = res_real.stats[PRIMARY]
    primary_trim = res_trimmed.stats[PRIMARY]
    lines += [
        "",
        "## Headline",
        f"- N (K>=2, full window): {res_real.n_events}",
        f"- gross primary {PRIMARY}: mean={primary_gross.mean * 100:+.2f}% t={primary_gross.t_stat:+.2f}",
        f"- after-cost primary {PRIMARY}: mean={primary_ac.mean * 100:+.2f}% t={primary_ac.t_stat:+.2f}",
        f"- drop-top-5 primary {PRIMARY}: mean={primary_trim.mean * 100:+.2f}% t={primary_trim.t_stat:+.2f}",
        "",
    ]
    text = "\n".join(lines) + "\n"
    RESULTS_PATH.write_text(text)
    print(text)
    print(f"\nResults: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
