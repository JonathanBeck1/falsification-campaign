#!/usr/bin/env python
"""Run the pre-registered turn-of-month effect study (T48).

Free data only (yfinance via trader.catalysts.prices). Thin runner: all stats
live in trader.catalysts.turn_of_month (pure, unit-tested).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.prices import fetch_daily  # noqa: E402
from trader.catalysts.turn_of_month import (  # noqa: E402
    PER_DAY_COST,
    compute_tom,
    evaluate_gate,
    placebo_diffs,
)

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

# Pre-registered parameters (research/turn_of_month_preregistration.md).
PRIMARY = "SPY"
CROSSCHECK = "^GSPC"
SINCE = date(1993, 1, 1)
UNTIL = date(2025, 12, 31)
IS_END = date(2009, 12, 31)   # IS = inception..2009; OOS = 2010..2025
N_PLACEBO = 1000

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "turn_of_month_decision.md"
JSON_PATH = OUT_DIR / "turn_of_month_study.json"
RAW_PATH = ROOT / "data" / "turn_of_month_results.txt"


def _returns(ticker: str) -> pd.Series | None:
    px = fetch_daily(ticker, SINCE, UNTIL)
    if px is None:
        return None
    close, _ = px
    r = close.pct_change().dropna()
    r.name = ticker
    return r


def _annualized_sharpe_long_tom(returns: pd.Series) -> float:
    """Sharpe of a long-on-TOM / flat-on-ROM daily rule (gross), annualized."""
    from trader.catalysts.turn_of_month import turn_of_month_mask

    r = returns.dropna()
    mask = turn_of_month_mask(r.index).reindex(r.index).fillna(False).to_numpy()
    strat = np.where(mask, r.to_numpy(), 0.0)
    sd = float(np.std(strat, ddof=1))
    if sd == 0.0:
        return 0.0
    return float(np.mean(strat) / sd * np.sqrt(252))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)

    spy = _returns(PRIMARY)
    if spy is None or spy.empty:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 2

    full = compute_tom(spy)
    is_r = compute_tom(spy[spy.index <= pd.Timestamp(IS_END)])
    oos_r = compute_tom(spy[spy.index > pd.Timestamp(IS_END)])

    placebo_t = placebo_diffs(spy, n_trials=N_PLACEBO, seed=12345)
    placebo_95 = float(np.percentile(np.abs(placebo_t), 95))
    placebo_mean_t = float(np.mean(placebo_t))

    verdict = evaluate_gate(full, is_r, oos_r, placebo_95)
    sharpe = _annualized_sharpe_long_tom(spy)

    # Cross-check on the longer ^GSPC index level (robustness, not a claim).
    gspc = _returns(CROSSCHECK)
    gspc_diff = gspc_t = float("nan")
    gspc_span = "unavailable"
    if gspc is not None and not gspc.empty:
        g = compute_tom(gspc)
        gspc_diff, gspc_t = g.diff, g.welch_t
        gspc_span = f"{gspc.index.min().date()}..{gspc.index.max().date()} (N={len(gspc)})"

    run_at = datetime.now(UTC).isoformat()

    def pct(x: float) -> str:
        return f"{x * 100:+.4f}%"

    raw_lines = [
        f"Turn-of-Month (T48) raw run — {run_at}",
        f"SPY span: {spy.index.min().date()}..{spy.index.max().date()} (N daily ret={len(spy)})",
        "",
        "FULL SAMPLE:",
        f"  TOM  n={full.tom.n} mean={pct(full.tom.mean)} median={pct(full.tom.median)} "
        f"%pos={full.tom.pct_positive:.3f} t0={full.tom.t_stat:+.2f}",
        f"  ROM  n={full.rom.n} mean={pct(full.rom.mean)} median={pct(full.rom.median)} "
        f"%pos={full.rom.pct_positive:.3f} t0={full.rom.t_stat:+.2f}",
        f"  TOM-ROM diff = {pct(full.diff)}  after-cost = {pct(full.after_cost_diff)}  "
        f"Welch t = {full.welch_t:+.2f}",
        f"  long-TOM/flat-ROM annualized Sharpe (gross) = {sharpe:.2f}",
        "",
        f"IS  ({SINCE}..{IS_END}):  TOM n={is_r.tom.n} diff={pct(is_r.diff)} Welch t={is_r.welch_t:+.2f}",
        f"OOS ({IS_END}+1..{UNTIL}): TOM n={oos_r.tom.n} diff={pct(oos_r.diff)} Welch t={oos_r.welch_t:+.2f}",
        "",
        f"PLACEBO ({N_PLACEBO} random pseudo-turn windows): "
        f"mean t={placebo_mean_t:+.2f}  95th-pct |t|={placebo_95:.2f}  "
        f"real |t|={abs(full.welch_t):.2f}",
        "",
        f"CROSS-CHECK {CROSSCHECK}: span {gspc_span}  TOM-ROM diff={pct(gspc_diff)} Welch t={gspc_t:+.2f}",
        "",
        "GATE:",
        *[f"  {r}" for r in verdict.reasons],
        f"  => {'PASS' if verdict.passed else 'FAIL'}",
    ]
    raw = "\n".join(raw_lines)
    print(raw)

    try:
        RAW_PATH.write_text(raw + "\n")
        JSON_PATH.write_text(
            json.dumps(
                {
                    "run_at": run_at,
                    "primary": PRIMARY,
                    "n_daily_returns": len(spy),
                    "full": {
                        "tom_n": full.tom.n,
                        "tom_mean": full.tom.mean,
                        "rom_n": full.rom.n,
                        "rom_mean": full.rom.mean,
                        "diff": full.diff,
                        "after_cost_diff": full.after_cost_diff,
                        "welch_t": full.welch_t,
                        "long_tom_sharpe": sharpe,
                    },
                    "is": {"tom_n": is_r.tom.n, "diff": is_r.diff, "welch_t": is_r.welch_t},
                    "oos": {"tom_n": oos_r.tom.n, "diff": oos_r.diff, "welch_t": oos_r.welch_t},
                    "placebo": {
                        "n_trials": N_PLACEBO,
                        "mean_t": placebo_mean_t,
                        "abs_t_95": placebo_95,
                    },
                    "crosscheck": {"ticker": CROSSCHECK, "diff": gspc_diff, "welch_t": gspc_t},
                    "per_day_cost": PER_DAY_COST,
                    "gate_passed": verdict.passed,
                    "gate_reasons": verdict.reasons,
                },
                indent=2,
                sort_keys=True,
                default=lambda o: None if (isinstance(o, float) and o != o) else o,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"ERROR: could not write study outputs: {exc}", file=sys.stderr)
        return 3

    print(f"\nRaw written: {RAW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
