#!/usr/bin/env python
"""End-to-end runner: does cloning 13F NEW positions from the FILING date work?

Pre-registration: research/thirteenf_clone_preregistration.md.

For a FROZEN list of well-known institutional 13F filers, pulls every 13F-HR
filing with ``filing_date`` in [2015-01-01, 2024-06-30], aggregates each filing's
equity-long holdings by CUSIP, and treats every NEW position (CUSIP absent from
the manager's immediately-preceding filing) as a clone event anchored on the
FILING date — the only ex-ante-tradeable timing. Measures market-adjusted CAR vs
SPY over [0,+21]/[0,+63]/[0,+126]/[0,+252] trading days. Controls: a placebo of
random non-event dates for the same names, and a 2015-20 / 2021-24 OOS split.
Writes research/thirteenf_clone_report.md.

THE STRUCTURAL KILLER under test: 13F is filed up to 45 days after quarter-end,
so by the filing date the information is ~1.5 months stale. We measure from the
filing date precisely to expose that lag.

Run from the worktree root:
  TRADER_SEC_USER_AGENT="name email" .venv/bin/python scripts/run_thirteenf_clone_study.py

Flags:
  --since YYYY-MM-DD   first filing date to include (default 2015-01-01)
  --until YYYY-MM-DD   last filing date to include (default 2024-06-30)
  --min-value USD      de-minimis filter on disclosed position value (default 5e6)
  --quick              tiny smoke sample (3 managers, 2019-2021) for a fast check
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

from trader.catalysts.prices import fetch_daily  # noqa: E402
from trader.catalysts.thirteenf_clone import (  # noqa: E402
    CAR_WINDOWS,
    PRIMARY,
    ROUND_TRIP_COST,
    CloneEvent,
    EventMetrics,
    Filing,
    Holding,
    aggregate,
    build_clone_events,
    compute_event_metrics,
    dedupe_events,
    evaluate_gate,
)

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

SINCE = date(2015, 1, 1)
UNTIL = date(2024, 6, 30)            # so 12mo forward (~to 2025-06) exists
OOS_SPLIT_YEAR = 2020               # filing year <= 2020 early, else late
MIN_VALUE = 5_000_000.0             # de-minimis disclosed position value
SEED = 12345

# ---- FROZEN universe: well-known long-biased equity 13F filers (CIK) -------- #
# Chosen for name recognition + long filing history. No performance selection.
MANAGERS: dict[str, str] = {
    "0001067983": "Berkshire Hathaway (Buffett)",
    "0001336528": "Pershing Square (Ackman)",
    "0001040273": "Third Point (Loeb)",
    "0001079114": "Greenlight Capital (Einhorn)",
    "0001006438": "Appaloosa (Tepper)",
    "0001061768": "Baupost Group (Klarman)",
    "0001412093": "Icahn Capital (Icahn)",
    "0001167483": "Lone Pine Capital",
    "0001603466": "Scion Asset Mgmt (Burry)",
    "0001656456": "Pershing Square Holdings",  # kept for breadth; deduped by event
    "0001135730": "Tiger Global Management",
    "0001167557": "Viking Global Investors",
}

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "thirteenf_clone_report.md"
RESULTS_PATH = ROOT / "data" / "thirteenf_clone_results.txt"

_LABELS = {
    "car_0_p21": "CAR +1m [0,+21]",
    "car_0_p63": "CAR +3m [0,+63] (PRIMARY)",
    "car_0_p126": "CAR +6m [0,+126]",
    "car_0_p252": "CAR +12m [0,+252]",
}


def _to_date(v) -> date | None:
    if v is None:
        return None
    try:
        return pd.Timestamp(v).date()
    except Exception:
        return None


def _aggregate_holdings(obj) -> list[Holding]:
    """Aggregate a 13F infotable to equity-long holdings by CUSIP (options out)."""

    try:
        df = obj.infotable
    except Exception:
        return None  # type: ignore[return-value]
    if df is None or len(df) == 0 or "Cusip" not in df.columns:
        return None  # type: ignore[return-value]
    df = df.copy()
    # equity LONG only: drop option/put rows (PutCall set)
    if "PutCall" in df.columns:
        df = df[df["PutCall"].fillna("").astype(str).str.strip() == ""]
    if len(df) == 0:
        return []
    df["Value"] = pd.to_numeric(df.get("Value"), errors="coerce").fillna(0.0)
    tcol = "Ticker" if "Ticker" in df.columns else None
    g = (
        df.groupby("Cusip")
        .agg(
            Value=("Value", "sum"),
            Ticker=(tcol, "first") if tcol else ("Cusip", "first"),
            Issuer=("Issuer", "first") if "Issuer" in df.columns else ("Cusip", "first"),
        )
        .reset_index()
    )
    out: list[Holding] = []
    for _, r in g.iterrows():
        tkr = str(r.get("Ticker") or "").strip().upper()
        out.append(
            Holding(
                cusip=str(r["Cusip"]).strip().upper(),
                ticker=tkr,
                issuer=str(r.get("Issuer") or "").strip(),
                value=float(r["Value"]),
            )
        )
    return out


def collect_filings(
    identity: str, managers: dict[str, str], since: date, until: date
) -> list[Filing]:
    """Pull 13F-HR filings per manager in [since, until]; reduce to Filing rows."""

    edgar.set_identity(identity)
    out: list[Filing] = []
    for j, (cik, name) in enumerate(managers.items()):
        try:
            company = edgar.Company(cik)
            fs = company.get_filings(form="13F-HR")
        except Exception as exc:
            log.warning("manager_filings_failed", cik=cik, name=name, error=str(exc))
            continue
        n_kept = 0
        for f in fs:
            fdate = _to_date(getattr(f, "filing_date", None))
            if fdate is None or not (since <= fdate <= until):
                continue
            try:
                obj = f.obj()
            except Exception:
                continue
            holdings = _aggregate_holdings(obj)
            if holdings is None:
                continue
            rperiod = _to_date(getattr(obj, "report_period", None)) or fdate
            out.append(
                Filing(
                    cik=str(cik),
                    manager=name,
                    filing_date=fdate,
                    report_period=rperiod,
                    holdings=tuple(holdings),
                )
            )
            n_kept += 1
        log.info(
            "manager_done", idx=j + 1, of=len(managers), cik=cik, name=name,
            filings_kept=n_kept, total_filings=len(out),
        )
    return out


def build_all_events(filings: list[Filing], min_value: float) -> list[CloneEvent]:
    """Build clone events per manager, then dedupe to one per (ticker, date)."""

    by_cik: dict[str, list[Filing]] = {}
    for f in filings:
        by_cik.setdefault(f.cik, []).append(f)
    raw: list[CloneEvent] = []
    for fs in by_cik.values():
        raw.extend(build_clone_events(fs, min_value=min_value))
    deduped = dedupe_events(raw)
    log.info("events_built", raw=len(raw), deduped=len(deduped))
    return deduped


def _placebo_date(
    close: pd.Series, real_dates: set[date], rng: random.Random
) -> date | None:
    """Random trading date for this name, >= 30 trading days from any real event,
    leaving a full forward window. None if none qualifies."""

    idx = pd.DatetimeIndex(close.dropna().sort_index().index)
    need_hi = max(w[1] for w in CAR_WINDOWS.values())
    if len(idx) < need_hi + 40:
        return None
    real_pos = [int(idx.searchsorted(pd.Timestamp(d))) for d in real_dates]
    candidates = [
        pos
        for pos in range(20, len(idx) - need_hi - 1)
        if all(abs(pos - rp) > 30 for rp in real_pos)
    ]
    if not candidates:
        return None
    return idx[rng.choice(candidates)].date()


def metrics_for_events(
    events: list[CloneEvent], spy_close: pd.Series, *, placebo: bool, seed: int
) -> tuple[list[EventMetrics], dict[str, int]]:
    """Fetch prices per ticker and compute CARs. Real or placebo events."""

    rng = random.Random(seed)
    by_ticker: dict[str, list[CloneEvent]] = {}
    for e in events:
        by_ticker.setdefault(e.ticker, []).append(e)

    out: list[EventMetrics] = []
    counts = {"no_price": 0, "no_window": 0, "no_placebo": 0, "ok": 0}
    names = sorted(by_ticker)
    for i, tkr in enumerate(names):
        if i % 25 == 0:
            log.info("price_progress", done=i, of=len(names), ok=len(out), placebo=placebo)
        es = by_ticker[tkr]
        lo = min(e.filing_date for e in es) - timedelta(days=60)
        hi = max(e.filing_date for e in es) + timedelta(days=430)
        px = fetch_daily(tkr, lo, hi)
        if px is None:
            counts["no_price"] += len(es)
            continue
        close, _vol = px
        real_dates = {e.filing_date for e in es}
        for e in es:
            if placebo:
                pdt = _placebo_date(close, real_dates, rng)
                if pdt is None:
                    counts["no_placebo"] += 1
                    continue
                m = compute_event_metrics(close, spy_close, e, event_date=pdt)
            else:
                m = compute_event_metrics(close, spy_close, e)
            if m is None:
                counts["no_window"] += 1
                continue
            out.append(m)
            counts["ok"] += 1
    return out, counts


def _table(result) -> str:
    rows = [
        "| window | n | mean % | median % | % pos | t-stat |",
        "|---|---|---|---|---|---|",
    ]
    for k in ("car_0_p21", "car_0_p63", "car_0_p126", "car_0_p252"):
        w = result.stats[k]
        rows.append(
            f"| {_LABELS[k]} | {w.n} | {w.mean * 100:+.2f} | {w.median * 100:+.2f} | "
            f"{w.pct_positive:.0%} | {w.t_stat:+.2f} |"
        )
    return "\n".join(rows)


def _top_contributors(metrics: list[EventMetrics], k: int = 5) -> list[EventMetrics]:
    return sorted(metrics, key=lambda m: m.car_0_p63, reverse=True)[:k]


def _mean_lag_days(events: list[CloneEvent]) -> float:
    lags = [(e.filing_date - e.report_period).days for e in events]
    return float(sum(lags) / len(lags)) if lags else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=str, default=SINCE.isoformat())
    ap.add_argument("--until", type=str, default=UNTIL.isoformat())
    ap.add_argument("--min-value", type=float, default=MIN_VALUE)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    identity = os.getenv("TRADER_SEC_USER_AGENT")
    if not identity:
        print("ERROR: set TRADER_SEC_USER_AGENT", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    managers = MANAGERS
    if args.quick:
        since, until = date(2019, 1, 1), date(2021, 6, 30)
        managers = dict(list(MANAGERS.items())[:3])

    log.info(
        "run_plan", since=str(since), until=str(until),
        n_managers=len(managers), min_value=args.min_value,
    )

    filings = collect_filings(identity, managers, since, until)
    pd.DataFrame(
        [
            {"cik": f.cik, "manager": f.manager, "filing_date": f.filing_date,
             "report_period": f.report_period, "n_holdings": len(f.holdings)}
            for f in filings
        ]
    ).to_csv(OUT_DIR / "thirteenf_filings.csv", index=False)
    log.info("filings_collected", n=len(filings))

    events = build_all_events(filings, args.min_value)
    pd.DataFrame([e.__dict__ for e in events]).to_csv(
        OUT_DIR / "thirteenf_clone_events.csv", index=False
    )
    mean_lag = _mean_lag_days(events)
    log.info("clone_events", n=len(events), mean_filing_lag_days=mean_lag)

    spy = fetch_daily("SPY", since - timedelta(days=120), until + timedelta(days=460))
    if spy is None:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 3
    spy_close, _ = spy

    real, real_counts = metrics_for_events(events, spy_close, placebo=False, seed=SEED)
    placebo, pl_counts = metrics_for_events(events, spy_close, placebo=True, seed=SEED)
    log.info("metrics_done", real=len(real), placebo=len(placebo))

    early = [m for m in real if m.filing_date.year <= OOS_SPLIT_YEAR]
    late = [m for m in real if m.filing_date.year > OOS_SPLIT_YEAR]

    # GROSS and AFTER-COST aggregations; the gate runs on AFTER-COST.
    res_gross = aggregate(real, label="real-gross")
    res_real = aggregate(real, label="real-net", cost=ROUND_TRIP_COST)
    res_placebo = aggregate(placebo, label="placebo-net", cost=ROUND_TRIP_COST)
    res_early = aggregate(early, label=f"oos<= {OOS_SPLIT_YEAR}", cost=ROUND_TRIP_COST)
    res_late = aggregate(late, label=f"oos> {OOS_SPLIT_YEAR}", cost=ROUND_TRIP_COST)
    verdict = evaluate_gate(res_real, res_placebo, res_early, res_late)

    # too-good tripwire / top-5 contributor inspection
    top5 = _top_contributors(real, 5)
    primary_vals = sorted([getattr(m, PRIMARY) for m in real], reverse=True)
    sum_top5 = sum(primary_vals[:5])
    sum_all = sum(primary_vals) if primary_vals else 0.0
    top5_share = (sum_top5 / sum_all) if sum_all not in (0.0,) else float("nan")

    n_names = len({e.ticker for e in events})
    lines = [
        "# 13F Institutional Cloning (filing-date) — Event Study Result",
        "",
        "Pre-registration: `research/thirteenf_clone_preregistration.md`.",
        "Market-adjusted CAR = stock return minus SPY (beta=1), summed over the",
        "trading-day window from the FILING date (the only ex-ante-tradeable",
        "timing). The 45-day disclosure lag is the structural reason this is",
        "expected to fail after cost.",
        "",
        "## Run metadata",
        f"- Managers (frozen, n={len(managers)}): {', '.join(managers.values())}",
        f"- Filing-date span: {since} .. {until}",
        f"- De-minimis position filter: ${args.min_value:,.0f}",
        f"- Benchmark: SPY | OOS split: filing year <= {OOS_SPLIT_YEAR} (early) vs > (late)",
        f"- Friction: {ROUND_TRIP_COST * 1e4:.0f} bps round-trip, subtracted per event",
        f"- Placebo: random non-event dates for the same names (seed={SEED})",
        f"- Mean filing lag (filing_date - report_period): {mean_lag:.1f} days",
        "",
        "## Sample accounting (count the dropouts honestly)",
        f"- 13F-HR filings kept: {len(filings)}",
        f"- Clone events (NEW positions, deduped by ticker+date): {len(events)} "
        f"across {n_names} distinct names",
        f"- Events with full [0,+252] price window (study N): {len(real)}",
        f"  - dropped, no yfinance price (delisted/unmatched ticker): {real_counts['no_price']}",
        f"  - dropped, short/incomplete forward window: {real_counts['no_window']}",
        f"- Placebo events built: {len(placebo)} (no placebo slot: {pl_counts['no_placebo']})",
        f"- OOS early (<= {OOS_SPLIT_YEAR}): {len(early)} | OOS late: {len(late)}",
        "",
        "> yfinance purges delisted tickers, so `no price` is a real,",
        "> survivorship-biased dropout: the survivors that remain are tilted UP,",
        "> which biases the test TOWARD the clone hypothesis. A kill is conservative.",
        "",
        "## Market-adjusted CAR vs SPY — clone events, GROSS",
        _table(res_gross),
        "",
        f"## After-cost ({ROUND_TRIP_COST * 1e4:.0f} bps round-trip) — the ranked view",
        _table(res_real),
        "",
        "## Placebo (random non-event dates, same names, after-cost)",
        _table(res_placebo),
        "",
        f"## OOS early (filing year <= {OOS_SPLIT_YEAR}, after-cost)",
        _table(res_early),
        "",
        f"## OOS late (filing year > {OOS_SPLIT_YEAR}, after-cost)",
        _table(res_late),
        "",
        "## Too-good tripwire / top-5 contributor inspection (PRIMARY, gross)",
        f"- Top-5 events contribute {top5_share:.0%} of the summed primary CAR.",
    ]
    for m in top5:
        lines.append(
            f"  - {m.ticker} ({m.manager}) filed {m.filing_date}: "
            f"{getattr(m, PRIMARY) * 100:+.1f}%"
        )
    lines += [
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
        f"Primary horizon is `{PRIMARY}` (~3 months). A real, tradeable clone",
        "signal needs: N>=30, a positive AFTER-COST primary CAR with |t|>=2, that",
        "BEATS the same-names placebo, and keeps its sign across the OOS split.",
        "The honest prior was null-to-negative: 13F's 45-day disclosure lag means",
        "the filing-date follower trades on ~1.5-month-stale information, exactly",
        "the window where any informed-trading edge would already be impounded.",
        "",
    ]
    report = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report)
    RESULTS_PATH.write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
