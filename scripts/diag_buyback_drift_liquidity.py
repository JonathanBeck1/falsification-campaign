#!/usr/bin/env python
"""Diagnostic for T41 buyback drift: is the passing gate a liquidity/cost mirage?

The pre-registered run PASSED (after-cost +1.08%, t=3.39, net-of-matched +1.52%,
OOS sign-stable). In a 19-for-19 kill campaign that means the artifact has not
yet been found, not that the edge is real. This diagnostic interrogates the
prime suspects (brain/30 classes #2 friction-scale, #3 data-glitch, #5/#6
baseline/composition):

  1. Size/liquidity composition of the cohort (price, $-volume).
  2. Realistic per-name cost (small caps cost FAR more than 15 bps).
  3. Liquidity-screened sub-cohort (only names a real book could trade).
  4. Winsorized + crypto-trust-excluded re-test (kill the glitch tail).
  5. Why the matched placebo is NEGATIVE (the net-of-matched inflator).

Free data only (EDGAR + yfinance), reusing the study's pure core.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.buyback_drift import (  # noqa: E402
    PRIMARY_WINDOW,
    abnormal_returns,
    aggregate,
    compute_event,
    mean,
    median,
    resolve_t0_index,
    std,
    t_stat_one_sample,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from run_buyback_drift_study import (  # noqa: E402
    SINCE,
    UNTIL,
    build_event_list,
)

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))

# Realistic single-name round-trip cost tiers by median daily dollar volume.
# Half-spread + impact; deliberately conservative-LOW so a kill is robust.
# (e.g. a $2M/day micro-cap pays ~150 bps round trip in practice; we use 150.)
def cost_for_dollar_vol(adv_usd: float) -> float:
    if adv_usd >= 50_000_000:  # large/liquid
        return 0.0010
    if adv_usd >= 10_000_000:
        return 0.0025
    if adv_usd >= 2_000_000:
        return 0.0060
    if adv_usd >= 500_000:
        return 0.0150
    return 0.0300  # sub-$500k/day: untradeable-ish, 300 bps floor


CRYPTO_TRUST_HINTS = {"ETCG", "BCHG", "GBTC", "ETHE", "OBTC", "LTCN", "GDLC"}


def main() -> int:
    filings, raw, complete = build_event_list()
    print(f"EDGAR: raw={raw} deduped={len(filings)} complete={complete}")

    spy = fetch_daily("SPY", SINCE - timedelta(days=40), UNTIL + timedelta(days=120))
    assert spy is not None
    spy_close, _ = spy

    by_ticker: dict[str, list] = {}
    for f in filings:
        by_ticker.setdefault(f.ticker, []).append(f)

    # rows: (ticker, t0_date, car_primary, adv_usd_at_event, price_at_event)
    rows: list[tuple[str, date, float, float, float]] = []
    for ticker, t_filings in by_ticker.items():
        lo = min(f.file_date for f in t_filings) - timedelta(days=20)
        hi = max(f.file_date for f in t_filings) + timedelta(days=160)
        prices = fetch_daily(ticker, lo, hi)
        if prices is None:
            continue
        close, volume = prices
        abn = abnormal_returns(close, spy_close)
        index = pd.DatetimeIndex(abn.index)
        for f in t_filings:
            ev = compute_event(abn, f.file_date, ticker)
            if ev is None:
                continue
            t0 = resolve_t0_index(index, f.file_date)
            if t0 is None or t0 < 21:
                adv = float("nan")
                px = float("nan")
            else:
                # 20-session trailing median $-volume and price BEFORE t0 (ex-ante).
                win_close = close.iloc[t0 - 20 : t0]
                win_vol = volume.reindex(win_close.index)
                dollar = (win_close * win_vol).dropna()
                adv = float(dollar.median()) if not dollar.empty else float("nan")
                px = float(close.iloc[t0 - 1])
            rows.append((ticker, ev.t0_date, ev.cars[PRIMARY_WINDOW], adv, px))

    cars = [r[2] for r in rows]
    print(f"\nN events with CARs: {len(rows)}")
    print(f"PRIMARY gross mean: {mean(cars) * 100:+.3f}%  median: {median(cars) * 100:+.3f}%")

    # 1. Size/liquidity composition
    advs = [r[3] for r in rows if r[3] == r[3]]
    pxs = [r[4] for r in rows if r[4] == r[4]]
    advs_sorted = sorted(advs)
    pxs_sorted = sorted(pxs)
    def pct(xs, p):
        return xs[int(p * (len(xs) - 1))] if xs else float("nan")
    print("\n--- LIQUIDITY COMPOSITION (trailing 20d median $-vol at event) ---")
    print(f"  events with adv: {len(advs)}")
    for p in (0.1, 0.25, 0.5, 0.75, 0.9):
        print(f"  adv p{int(p*100):02d}: ${pct(advs_sorted, p)/1e6:8.2f}M   "
              f"price p{int(p*100):02d}: ${pct(pxs_sorted, p):7.2f}")
    share_sub2m = sum(1 for a in advs if a < 2_000_000) / len(advs)
    share_sub10m = sum(1 for a in advs if a < 10_000_000) / len(advs)
    print(f"  share < $2M/day:  {share_sub2m*100:.1f}%")
    print(f"  share < $10M/day: {share_sub10m*100:.1f}%")

    # 2. Realistic per-name cost
    real_after = []
    for r in rows:
        adv = r[3]
        c = cost_for_dollar_vol(adv) if adv == adv else 0.0300
        real_after.append(r[2] - c)
    print("\n--- REALISTIC TIERED COST (vs pre-reg flat 15 bps) ---")
    print(f"  after realistic cost mean: {mean(real_after)*100:+.3f}%  "
          f"t={t_stat_one_sample(real_after):+.2f}")

    # 3. Liquidity-screened sub-cohort (tradeable only: >= $10M/day)
    liq = [r for r in rows if r[3] == r[3] and r[3] >= 10_000_000]
    liq_cars = [r[2] for r in liq]
    liq_after = [r[2] - cost_for_dollar_vol(r[3]) for r in liq]
    print(f"\n--- LIQUIDITY-SCREENED (>= $10M/day, N={len(liq)}) ---")
    print(f"  gross mean: {mean(liq_cars)*100:+.3f}%  median: {median(liq_cars)*100:+.3f}%")
    print(f"  after tiered cost: {mean(liq_after)*100:+.3f}%  t={t_stat_one_sample(liq_after):+.2f}")
    # OOS within liquid sub-cohort
    liq_is = [r[2] for r in liq if r[1].year < 2020]
    liq_oos = [r[2] for r in liq if r[1].year >= 2020]
    print(f"  IS mean {mean(liq_is)*100:+.3f}% (n={len(liq_is)}) | "
          f"OOS mean {mean(liq_oos)*100:+.3f}% (n={len(liq_oos)})")

    # 4. Winsorize + drop crypto trusts
    no_crypto = [r for r in rows if r[0] not in CRYPTO_TRUST_HINTS]
    nc_cars = sorted(r[2] for r in no_crypto)
    n = len(nc_cars)
    k = int(0.01 * n)
    wins = nc_cars[k : n - k] if n > 2 * k else nc_cars
    print(f"\n--- DROP CRYPTO TRUSTS + 1% WINSORIZE (N={len(wins)}) ---")
    print(f"  winsorized gross mean: {mean(wins)*100:+.3f}%  median: {median(wins)*100:+.3f}%")
    print(f"  winsorized after 15bps: {mean([w-0.0015 for w in wins])*100:+.3f}%  "
          f"t={t_stat_one_sample([w-0.0015 for w in wins]):+.2f}")

    # 5. Mean vs median diagnosis (right-skew = small-cap pop tail)
    s = aggregate(cars, label="all")
    print("\n--- SKEW DIAGNOSIS ---")
    print(f"  mean {s.gross_mean*100:+.3f}% vs median {s.median*100:+.3f}% "
          f"(mean>>median => right-skew tail) | std {std(cars)*100:.2f}% win {s.win_rate*100:.1f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
