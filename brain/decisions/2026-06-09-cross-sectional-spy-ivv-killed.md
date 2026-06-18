# Decision: Cross-sectional lab's 28 "survivors" are an artifact, not edge

Date: 2026-06-09
Status: killed by friction analysis. Cross-sectional pair lab counted as null.

## What appeared

The cross-sectional mining lab (290 variants, OOS split 2019) reported **28
deflation-cleared, OOS-confirmed survivors** — the first non-zero result in the
entire mining campaign. Top variant: `pair_SPY_IVV_W20_z1.0_h5` IS Sharpe 4.26,
OOS 2.54, DSR 1.00.

## Why it's not real

1. **All 28 survivors are SPY/IVV variants + one HYG/JNK** — same underlying
   signal at different parameters, not independent finds.
2. **SPY and IVV are both S&P 500 trackers** from different issuers (SPDR vs
   iShares). Daily return correlation: **0.9988**. They are economically the
   same fund.
3. **The "alpha" lives entirely in 2-5 bps of daily microstructure noise**
   (mean abs daily SPY-IVV diff = 2.88 bps; stdev = 5.41 bps). Round-trip
   frictions on the pair (bid/ask + impact) are ~5 bps. Net of realistic
   transaction costs, the signal is **zero or negative**.
4. **HYG/JNK is identical case** — both broad high-yield bond ETFs.

## The general lesson

`run_lab()` is cost-free by design — fine for strategies on distinct assets
where typical alpha is much larger than per-trade frictions. **For pair trades
on near-identical assets, the entire signal is at the friction scale,** and
zero-cost Sharpe estimates are meaningless. The deflated-Sharpe gate caught the
statistical phenomenon as "real" — which it is — but did NOT catch that it's
uncapturable by a retail follower.

## The action

- **Documented as kill.** Not added to the dashboard's survivor count.
- **Add a `friction_suspect=True` flag** to the cross-sectional pair-family
  output so the dashboard can grey out near-identical-asset survivors. (Future
  work; not blocking the broader campaign.)
- **Lab v2 idea**: an optional `cost_bps` parameter to `run_lab()` that
  subtracts a per-day friction estimate from each variant's returns. Defer
  until another near-friction survivor appears.

## Net effect on the mining campaign

The "first survivor" was a textbook artifact, caught by reasoning rather than by
the machine. The lab still needs the friction layer; until then, treat
pair-trade survivors with extreme skepticism. The campaign-level result stands:
**no real edge across the spaces tested** — including this one once costs are
honestly accounted for.
