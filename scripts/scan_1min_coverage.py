#!/usr/bin/env python
"""Day-level 1-min option-quote coverage scan, 2020-2025 (Phase 4 prerequisite).

The depth probe (2026-06-11) found vendor-side day-level holes in 1-min option
quotes (e.g. 2022-05-16, 2022-06-13/14/17, 2022-07-05) while EOD serves fine.
Before any chain backfill, enumerate EVERY missing day so the backfill ledger
can mark them MISSING_VENDOR instead of retrying forever, and so per-regime
results can report coverage %.

Method, per SPY trading day (from yfinance daily closes):
  - exp     = nearest listed expiration in [day+10, day+45] (from /v2/list/expirations)
  - strike  = nearest listed strike to that day's close (from /v2/list/strikes)
  - request 1-min NBBO (ivl=60000) for that single call contract
  - on "no data": retry two neighboring strikes before declaring the day MISSING

Output: output/coverage_1min_spy.json + research/coverage_1min_2020_2025.md
"""

from __future__ import annotations

import bisect
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:25510"
OUT_JSON = ROOT / "output" / "coverage_1min_spy.json"
OUT_MD = ROOT / "research" / "coverage_1min_2020_2025.md"
START, END = "2020-01-01", "2025-12-31"


def get(path: str, params: dict) -> tuple[dict | None, str | None]:
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=60)
    except Exception as e:
        return None, f"request: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:120]}"
    j = r.json()
    err = (j.get("header") or {}).get("error_type")
    if err and err != "null":
        return None, f"{err}"
    return j, None


def main() -> int:
    import yfinance as yf
    spy = yf.download("SPY", start=START, end=END, auto_adjust=True,
                      progress=False, threads=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy = spy.droplevel(axis=1, level=1)
    closes = spy["Close"].dropna()
    days = [(d.strftime("%Y%m%d"), float(c)) for d, c in closes.items()]
    print(f"trading days to scan: {len(days)}", flush=True)

    j, err = get("/v2/list/expirations", {"root": "SPY"})
    if err:
        print(f"FATAL: expirations: {err}")
        return 2
    exps = sorted(int(e) for e in j["response"])
    exp_dates = [pd.Timestamp(str(e)) for e in exps]

    strikes_cache: dict[int, list[int]] = {}

    def listed_strikes(exp: int) -> list[int]:
        if exp not in strikes_cache:
            jj, e2 = get("/v2/list/strikes", {"root": "SPY", "exp": exp})
            strikes_cache[exp] = sorted(int(s) for s in jj["response"]) if not e2 else []
        return strikes_cache[exp]

    results = []
    t_start = time.time()
    for i, (day, close) in enumerate(days):
        d = pd.Timestamp(day)
        # nearest listed expiration 10-45 calendar days out
        lo = bisect.bisect_left(exp_dates, d + pd.Timedelta(days=10))
        exp = None
        for k in range(lo, min(lo + 30, len(exp_dates))):
            if (exp_dates[k] - d).days <= 45:
                exp = exps[k]
                break
        if exp is None:
            results.append({"date": day, "status": "NO_EXP"})
            continue
        ks = listed_strikes(exp)
        if not ks:
            results.append({"date": day, "status": "NO_STRIKES", "exp": exp})
            continue
        target = round(close) * 1000
        pos = min(bisect.bisect_left(ks, target), len(ks) - 1)
        tries = [ks[pos]]
        if pos > 0:
            tries.append(ks[pos - 1])
        if pos + 1 < len(ks):
            tries.append(ks[pos + 1])
        status, rows = "MISSING", 0
        for strike in tries:
            jj, e2 = get("/v2/hist/option/quote", {
                "root": "SPY", "exp": exp, "strike": strike, "right": "C",
                "start_date": day, "end_date": day, "ivl": 60000,
            })
            if e2 is None:
                rows = len(jj.get("response") or [])
                if rows > 0:
                    status = "OK"
                    break
            elif "permission" in e2.lower() or "471" in e2:
                status = "PERMISSION"
                break
        results.append({"date": day, "status": status, "exp": exp, "rows": rows})
        if (i + 1) % 50 == 0:
            n_miss = sum(1 for r in results if r["status"] != "OK")
            rate = (i + 1) / (time.time() - t_start)
            print(f"{i + 1}/{len(days)} scanned, {n_miss} not-OK, {rate:.1f} days/s", flush=True)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1))

    df = pd.DataFrame(results)
    df["year"] = df.date.str[:4]
    lines = ["# 1-min option quote coverage, SPY 2020-2025", "",
             "Day-level scan of ThetaData 1-min NBBO availability (ATM call probe,",
             "3-strike retry before declaring a day missing).",
             "Script: `scripts/scan_1min_coverage.py`.", ""]
    lines.append("| year | trading days | OK | missing | coverage |")
    lines.append("|---|---:|---:|---:|---:|")
    for y, g in df.groupby("year"):
        ok = int((g.status == "OK").sum())
        lines.append(f"| {y} | {len(g)} | {ok} | {len(g) - ok} | {ok / len(g) * 100:.1f}% |")
    bad = df[df.status != "OK"]
    lines += ["", f"## Missing days ({len(bad)})", ""]
    for _, r in bad.iterrows():
        lines.append(f"- {r.date}: {r.status}")
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {OUT_MD}")
    print(f"total missing: {len(bad)}/{len(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
