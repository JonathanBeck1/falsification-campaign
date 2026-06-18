#!/usr/bin/env python
"""Matched-control test for the product_news__up Phase 2 survivor.

Pre-registered design (before running):

  H0: the +8.15% raw CAR[+1,+21] of product_news__up (N=48) is explained by
      ticker/year composition — i.e. the cohort is NVDA/TSLA-heavy in big drift
      years, and ANY same-(ticker, year) day shows the same drift.

  Test 1 — matched-control net drift:
      For each event, baseline = mean CAR[+1,+21] over ALL eligible control
      days for the same ticker in the same calendar year (excluding any day
      within ±5 trading days of ANY catalog event for that ticker).
      net_i = event_CAR_i - baseline(ticker_i, year_i)
      Report mean(net), t-stat. Survivor requires mean net > 0 with |t| >= 2.

  Test 2 — composition-matched permutation:
      2,000 placebo cohorts of N=48, each drawing one random eligible control
      day per event from the SAME (ticker, year) cell. p-value = fraction of
      placebo cohort means >= observed raw cohort mean. Survivor requires
      p < 0.05 after this composition correction.

  Test 3 — classifier-leak probe:
      Split events by LLM confidence (high vs medium/low). If high-confidence
      events show materially larger drift, classification confidence is
      leaking hindsight (the classifier 'knows' which events mattered).
      This is diagnostic, not a gate.

  Seed fixed at 7 for reproducibility.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

CLEAN_CATALOG = ROOT / "output" / "catalysts" / "news_catalog_clean.parquet"
REPORT = ROOT / "research" / "product_news_control_report.md"
RESULTS_JSON = ROOT / "output" / "catalysts" / "product_news_control_results.json"
PRICE_START = "2019-11-01"
PRICE_END = "2026-06-10"
SEED = 7
N_PERMUTATIONS = 2000
EXCLUDE_RADIUS = 5  # trading days around ANY catalog event for that ticker
WINDOW = 21


def fetch_close(ticker: str) -> pd.Series | None:
    import yfinance as yf
    try:
        df = yf.download(ticker, start=PRICE_START, end=PRICE_END,
                         auto_adjust=True, progress=False, threads=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)
    s = df["Close"].dropna()
    s.index = pd.DatetimeIndex(s.index)
    return s


def car21_series(close: pd.Series, spy: pd.Series) -> pd.Series:
    """car21[t0] = sum of market-adjusted ARs over [t0+1, t0+21].

    Same definition as phase2.compute_drift_for_event, vectorized over all t0.
    NaN where the forward window is incomplete.
    """
    close = close.dropna().sort_index()
    r = close.pct_change()
    s = spy.reindex(close.index).ffill().pct_change()
    ar = (r - s).fillna(0.0)
    csum = ar.cumsum()
    # sum over [t0+1, t0+21] = csum[t0+21] - csum[t0]
    fwd = csum.shift(-WINDOW) - csum
    # invalidate t0 where t0+21 runs off the end
    fwd.iloc[len(fwd) - WINDOW:] = np.nan
    return fwd


def main() -> int:
    rng = np.random.default_rng(SEED)
    catalog = pd.read_parquet(CLEAN_CATALOG)
    catalog["date"] = pd.to_datetime(catalog["date"])

    cohort = catalog[(catalog.category == "product_news") & (catalog.direction == "up")].copy()
    print(f"product_news__up events: {len(cohort)}", flush=True)
    print("\nticker composition:")
    comp = cohort.ticker.value_counts()
    for t, n in comp.items():
        print(f"  {t}: {n}")
    print("\nyear composition:")
    for y, n in cohort.date.dt.year.value_counts().sort_index().items():
        print(f"  {y}: {n}")

    tickers = sorted(cohort.ticker.unique())
    closes: dict[str, pd.Series] = {}
    for t in [*tickers, "SPY"]:
        s = fetch_close(t)
        if s is None:
            print(f"ERROR: no prices for {t}", file=sys.stderr)
            return 2
        closes[t] = s
    spy = closes["SPY"]

    # Precompute CAR21 for every ticker/day
    car: dict[str, pd.Series] = {t: car21_series(closes[t], spy) for t in tickers}

    # Eligible control days per ticker: valid CAR, not within ±5 trading days
    # of ANY catalog event (any category/direction) for that ticker.
    controls: dict[str, pd.Series] = {}
    for t in tickers:
        s = car[t].dropna()
        idx = s.index
        mask = np.ones(len(idx), dtype=bool)
        ev_dates = catalog[catalog.ticker == t].date
        for d in ev_dates:
            pos = idx.searchsorted(d)
            lo, hi = max(0, pos - EXCLUDE_RADIUS), min(len(idx), pos + EXCLUDE_RADIUS + 1)
            mask[lo:hi] = False
        controls[t] = s[mask]
        print(f"  {t}: {len(s)} valid days, {len(controls[t])} eligible controls")

    # Per-event: event CAR + matched (ticker, year) control mean
    rows = []
    for _, ev in cohort.iterrows():
        t, d = ev["ticker"], ev["date"]
        s = car[t]
        if d not in s.index or not np.isfinite(s.loc[d]):
            continue
        year = d.year
        ctrl = controls[t]
        cell = ctrl[ctrl.index.year == year]
        if len(cell) < 20:  # too few matched controls -> widen to ±1 year
            cell = ctrl[(ctrl.index.year >= year - 1) & (ctrl.index.year <= year + 1)]
        rows.append({
            "ticker": t,
            "date": str(d.date()),
            "year": year,
            "confidence": ev["confidence"],
            "event_car": float(s.loc[d]),
            "ctrl_mean": float(cell.mean()),
            "n_ctrl": len(cell),
            "net": float(s.loc[d] - cell.mean()),
        })
    ev_df = pd.DataFrame(rows)
    n = len(ev_df)
    print(f"\nevents with computable matched control: {n}")

    raw_mean = ev_df.event_car.mean()
    ctrl_mean = ev_df.ctrl_mean.mean()
    net = ev_df.net
    net_mean = net.mean()
    net_t = float(net.mean() / (net.std(ddof=1) / np.sqrt(n))) if n > 1 else 0.0

    print("\n=== TEST 1: matched-control net drift ===")
    print(f"raw cohort CAR[+1,+21]:        {raw_mean*100:+.2f}%")
    print(f"matched (ticker,yr) baseline:  {ctrl_mean*100:+.2f}%")
    print(f"NET drift:                     {net_mean*100:+.2f}%  t={net_t:+.2f}")

    # Test 2: composition-matched permutation
    cells: list[np.ndarray] = []
    for _, ev in ev_df.iterrows():
        ctrl = controls[ev["ticker"]]
        cell = ctrl[ctrl.index.year == ev["year"]]
        if len(cell) < 20:
            cell = ctrl[(ctrl.index.year >= ev["year"] - 1) & (ctrl.index.year <= ev["year"] + 1)]
        cells.append(cell.to_numpy())
    placebo_means = np.empty(N_PERMUTATIONS)
    for i in range(N_PERMUTATIONS):
        draw = [c[rng.integers(0, len(c))] for c in cells]
        placebo_means[i] = float(np.mean(draw))
    p_value = float((placebo_means >= raw_mean).mean())

    print(f"\n=== TEST 2: composition-matched permutation ({N_PERMUTATIONS} cohorts) ===")
    print(f"placebo cohort mean: {placebo_means.mean()*100:+.2f}%  (sd {placebo_means.std()*100:.2f}%)")
    print(f"placebo 95th pct:    {np.percentile(placebo_means, 95)*100:+.2f}%")
    print(f"observed raw mean:   {raw_mean*100:+.2f}%")
    print(f"p-value (>= observed): {p_value:.4f}")

    # Test 3: classifier-leak probe
    hi = ev_df[ev_df.confidence == "high"]
    lo = ev_df[ev_df.confidence != "high"]
    print("\n=== TEST 3: classifier-leak probe ===")
    print(f"high confidence:   N={len(hi)}  raw {hi.event_car.mean()*100:+.2f}%  net {hi.net.mean()*100:+.2f}%")
    print(f"med/low confidence: N={len(lo)}  raw {lo.event_car.mean()*100:+.2f}%  net {lo.net.mean()*100:+.2f}%")

    verdict_net = abs(net_t) >= 2.0 and net_mean > 0
    verdict_perm = p_value < 0.05
    survives = verdict_net and verdict_perm
    print("\n=== VERDICT ===")
    print(f"Test 1 (|t|>=2 on net): {'PASS' if verdict_net else 'FAIL'}")
    print(f"Test 2 (perm p<0.05):   {'PASS' if verdict_perm else 'FAIL'}")
    print(f"product_news__up {'SURVIVES matched-control' if survives else 'KILLED by matched-control'}")

    # Persist
    RESULTS_JSON.write_text(json.dumps({
        "n_events": n,
        "raw_mean_car": raw_mean,
        "matched_ctrl_mean": ctrl_mean,
        "net_mean": net_mean,
        "net_t": net_t,
        "perm_p_value": p_value,
        "placebo_mean": float(placebo_means.mean()),
        "placebo_sd": float(placebo_means.std()),
        "placebo_p95": float(np.percentile(placebo_means, 95)),
        "high_conf": {"n": len(hi), "raw": float(hi.event_car.mean()), "net": float(hi.net.mean())},
        "med_low_conf": {"n": len(lo), "raw": float(lo.event_car.mean()), "net": float(lo.net.mean())},
        "ticker_composition": comp.to_dict(),
        "survives": survives,
        "events": ev_df.to_dict(orient="records"),
    }, indent=2, default=str))

    lines = [
        "# product_news__up — matched-control test",
        "",
        "Design: per-event baseline = mean CAR[+1,+21] over all eligible control days",
        f"for the SAME ticker in the SAME calendar year (excluding ±{EXCLUDE_RADIUS} trading days",
        "around any catalog event for that ticker). Permutation: 2,000 placebo cohorts",
        "with identical (ticker, year) composition. Seed=7, pre-registered gates:",
        "net |t|>=2 AND permutation p<0.05.",
        "",
        f"- Events: **{n}**",
        f"- Raw cohort CAR[+1,+21]: **{raw_mean*100:+.2f}%**",
        f"- Matched (ticker, year) baseline: **{ctrl_mean*100:+.2f}%**",
        f"- **Net drift: {net_mean*100:+.2f}% (t={net_t:+.2f})** — {'PASS' if verdict_net else 'FAIL'}",
        f"- Permutation p-value: **{p_value:.4f}** (placebo mean {placebo_means.mean()*100:+.2f}%, "
        f"95th pct {np.percentile(placebo_means, 95)*100:+.2f}%) — {'PASS' if verdict_perm else 'FAIL'}",
        "",
        f"## Verdict: **{'SURVIVES' if survives else 'KILLED'}**",
        "",
        "## Classifier-leak probe (diagnostic)",
        "",
        f"- high confidence: N={len(hi)}, raw {hi.event_car.mean()*100:+.2f}%, net {hi.net.mean()*100:+.2f}%",
        f"- med/low confidence: N={len(lo)}, raw {lo.event_car.mean()*100:+.2f}%, net {lo.net.mean()*100:+.2f}%",
        "",
        "## Ticker composition",
        "",
    ]
    for t, c in comp.items():
        lines.append(f"- {t}: {c}")
    lines += ["", "## Per-event detail", "", "| ticker | date | conf | event CAR % | ctrl mean % | net % |",
              "|---|---|---|---:|---:|---:|"]
    for _, r in ev_df.sort_values("net", ascending=False).iterrows():
        lines.append(f"| {r.ticker} | {r.date} | {r.confidence} | {r.event_car*100:+.2f} | "
                     f"{r.ctrl_mean*100:+.2f} | {r.net*100:+.2f} |")
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"\nreport: {REPORT}")
    print(f"json:   {RESULTS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
