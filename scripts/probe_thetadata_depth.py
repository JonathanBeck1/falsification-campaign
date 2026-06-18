#!/usr/bin/env python
"""Phase 0 probe: how deep does our ThetaData subscription actually go?

brain/25's options OOS protocol assumes historical option quotes exist for
Feb-2018 (volmageddon), Mar-2020 (COVID crash), and 2022 (bear). This probe
verifies that assumption against the local ThetaTerminal REST API before any
backfill engineering happens.

Per (root, date, expiration):
  1. bulk EOD:   /v2/bulk_hist/option/eod   -> how many contracts have data?
  2. 1-min NBBO: /v2/hist/option/quote ivl=60000 on an ATM-ish contract picked
     from the bulk response -> row count + fraction with a live two-sided quote.

The condor engine needs 1-min NBBO specifically, so (2) is the binding check.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:25510"
REPORT = ROOT / "research" / "thetadata_depth_probe.md"
RESULTS_JSON = ROOT / "output" / "thetadata_depth_probe.json"

# (label, root, probe_date YYYYMMDD, expiration YYYYMMDD)
PROBES = [
    ("volmageddon-2018", "SPY", "20180206", "20180316"),
    ("volmageddon-2018", "QQQ", "20180206", "20180316"),
    ("covid-crash-2020", "SPY", "20200316", "20200417"),
    ("covid-crash-2020", "QQQ", "20200316", "20200417"),
    ("bear-2022", "SPY", "20220613", "20220715"),
    ("bear-2022", "QQQ", "20220613", "20220715"),
    ("control-recent", "SPY", "20260515", "20260618"),
    ("control-recent", "QQQ", "20260515", "20260618"),
]


def get(path: str, params: dict) -> tuple[dict | None, str | None]:
    """Returns (json, error_string)."""
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=90)
    except Exception as e:
        return None, f"request failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    try:
        j = r.json()
    except Exception:
        return None, f"non-JSON response: {r.text[:200]}"
    err = (j.get("header") or {}).get("error_type")
    if err and err != "null":
        return None, f"{err}: {(j.get('header') or {}).get('error_msg', '')[:200]}"
    return j, None


def probe_one(label: str, root: str, day: str, exp: str) -> dict:
    out: dict = {"label": label, "root": root, "date": day, "exp": exp}

    # 1. Bulk EOD across the chain for that expiration on that day
    j, err = get("/v2/bulk_hist/option/eod", {
        "root": root, "exp": exp, "start_date": day, "end_date": day,
    })
    if err:
        out["eod_error"] = err
        out["eod_contracts"] = 0
    else:
        resp = j.get("response") or []
        out["eod_contracts"] = len(resp)
        # pick a middle-of-chain contract (ATM-ish) for the 1-min probe
        strikes = sorted({c["contract"]["strike"] for c in resp if c.get("contract")})
        out["strike_range"] = [strikes[0] / 1000, strikes[-1] / 1000] if strikes else None
        if strikes:
            out["probe_strike"] = strikes[len(strikes) // 2]

    # 2. 1-min NBBO on the picked contract
    strike = out.get("probe_strike")
    if not strike:
        out["quote_rows"] = 0
        out["quote_error"] = out.get("eod_error", "no contract available to probe")
        return out
    j, err = get("/v2/hist/option/quote", {
        "root": root, "exp": exp, "strike": strike, "right": "C",
        "start_date": day, "end_date": day, "ivl": 60000,
    })
    if err:
        out["quote_error"] = err
        out["quote_rows"] = 0
        return out
    cols = (j.get("header") or {}).get("format") or []
    rows = j.get("response") or []
    out["quote_rows"] = len(rows)
    try:
        bid_i, ask_i = cols.index("bid"), cols.index("ask")
        live = sum(1 for r in rows if r[bid_i] > 0 and r[ask_i] > 0)
        out["pct_two_sided"] = round(live / len(rows), 3) if rows else 0.0
        mid = rows[len(rows) // 2]
        out["sample_quote"] = {"bid": mid[bid_i], "ask": mid[ask_i]}
    except (ValueError, IndexError):
        out["pct_two_sided"] = None
    return out


def main() -> int:
    results = []
    for label, root, day, exp in PROBES:
        print(f"probing {label} {root} {day} exp={exp} ...", flush=True)
        r = probe_one(label, root, day, exp)
        results.append(r)
        strike = r.get("probe_strike")
        print(f"  eod_contracts={r.get('eod_contracts')} "
              f"strike={strike / 1000 if strike else None} "
              f"quote_rows={r.get('quote_rows')} "
              f"two_sided={r.get('pct_two_sided')} "
              f"err={r.get('eod_error') or r.get('quote_error') or '-'}", flush=True)

    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(results, indent=2))

    # Verdict: a regime date "has depth" if both roots return 1-min quotes
    # with mostly two-sided markets.
    def ok(r: dict) -> bool:
        return r.get("quote_rows", 0) >= 300 and (r.get("pct_two_sided") or 0) >= 0.8

    by_label: dict[str, list[dict]] = {}
    for r in results:
        by_label.setdefault(r["label"], []).append(r)

    lines = ["# ThetaData historical depth probe (Phase 0)", "",
             "Binding check: 1-min NBBO (what the condor engine consumes), not EOD.",
             "Pass = >=300 one-min rows AND >=80% two-sided quotes for both SPY and QQQ.",
             ""]
    lines.append("| regime | root | EOD contracts | 1-min rows | % two-sided | error |")
    lines.append("|---|---|---:|---:|---:|---|")
    verdicts = {}
    for label, rs in by_label.items():
        for r in rs:
            lines.append(
                f"| {label} | {r['root']} | {r.get('eod_contracts', 0)} | "
                f"{r.get('quote_rows', 0)} | "
                f"{(r.get('pct_two_sided') or 0) * 100:.0f}% | "
                f"{r.get('eod_error') or r.get('quote_error') or '-'} |"
            )
        verdicts[label] = all(ok(r) for r in rs)
    lines += ["", "## Verdict per regime", ""]
    for label, v in verdicts.items():
        lines.append(f"- {label}: {'✅ DEPTH CONFIRMED' if v else '❌ INSUFFICIENT'}")
    regime_labels = [lbl for lbl in verdicts if lbl != "control-recent"]
    n_ok = sum(verdicts[lbl] for lbl in regime_labels)
    lines += ["", f"## Overall: {n_ok}/{len(regime_labels)} regime dates have 1-min depth", ""]
    if not verdicts.get("control-recent", False):
        lines.append("⚠️ Control date FAILED — probe method or terminal state is suspect; "
                     "do not trust the regime verdicts until the control passes.")
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"\nreport: {REPORT}")
    print(f"json:   {RESULTS_JSON}")
    for label in by_label:
        print(f"{label}: {'OK' if verdicts[label] else 'INSUFFICIENT'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
