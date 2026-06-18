# Options Backtesting — State, Strategy & Math

**Date:** 2026-06-05 · **Status:** current
**Read this with `docs/BUILD_PLAN.md`.** This is the honest state of the options backtesting:
which results you can trust, the exact strategy, and the exact math behind every number.

---

## ⚠️ TL;DR — read this first

We ran **many** backtests; most came from a **broken engine** and are artifacts. After two
rounds of fixes (#101 realism + #104 fake-win), we now have **trustworthy** numbers for the
no-stop 16-delta iron condor across three regimes — and the verdict is clear:

| Year (regime) | Trades | Win% | **Total P&L** | Profit factor |
|---|---:|---:|---:|---:|
| 2020 (COVID crash + recovery) | 21 | 28.6% | **−$1,632** | 0.17 |
| 2021 (calm bull) | 21 | 42.9% | **−$1,141** | 0.15 |
| 2022 (−34% bear) | 19 | 36.8% | **−$1,216** | 0.17 |

**This configuration loses in every regime** (~−$1,300/yr, profit factor ~0.16; ~−$4k over
3 years / 61 trades). The most damning point: **2021 was a calm bull year — the ideal
environment for a short-vol condor — and it still lost $1,141.** Almost no trades reach the
profit target; they ride to the 21-DTE time-exit and realize losses the small credit can't
outrun after costs.

This is a **trustworthy NEGATIVE result** — from a realistic-but-optimistic engine, so a loss
here is a real loss. **Do not trade this configuration.** Whether *any* condor configuration
has an edge is the open question for an expectancy-ranked parameter sweep (or a pivot); §5.

> ### The −$42 you may have seen was wrong
> An earlier "trustworthy" run reported **−$42 / 68% win** for 2022. It was inflated ~30× by a
> fake-win bug (#104): when an open OTM condor's leg quotes momentarily
> vanished, the engine settled it to $0 and booked a **fabricated max-profit win**. Fixing it
> removed every fabricated `profit_target` win — the true 2022 number is **−$1,216 / 37%**.
> Lesson: even a "realistic" number is only as good as the marking underneath it.

Why the older numbers are garbage is in §4: the old engine marked off sparse/stale quotes
(producing **impossible P&L** larger than the max loss) and **cherry-picked exits** (always
"selling" at the single best minute of the day, which no real trader can do).

---

## 1. Every backtest we've run (P&L table)

All P&L is in **dollars** (each option contract = 100 shares, so a $1.00 credit = $100).

| Report (research/*.md) | Period | Stop | Trades | Win% | **Total P&L** | MaxDD | PF | Trust |
|---|---|---|---:|---:|---:|---:|---:|:---:|
| **bt_qqq_nostop_2020_clean** | 2020 | none | 21 | 28.6% | **−$1,632** | $1,709 | 0.17 | ✅ **REAL** |
| **bt_qqq_nostop_2021_clean** | 2021 | none | 21 | 42.9% | **−$1,141** | $1,186 | 0.15 | ✅ **REAL** |
| **bt_qqq_nostop_2022_clean** | 2022 | none | 19 | 36.8% | **−$1,216** | $1,216 | 0.17 | ✅ **REAL** |
| bt_qqq_nostop_2022_realistic | 2022 | none | 25 | 68% | −$42 | $441 | 0.96 | ⚠️ stale³ |
| bt_qqq_nostop_2022_fixed | 2022 | none | 118 | 96.6% | +$12,983 | $229 | 50.0 | ⚠️ partial¹ |
| nostop_2022 | 2022 | none | 111 | 95.5% | +$11,349 | $976 | 10.4 | ❌ broken |
| bt_qqq_2022 | 2022 | 2× | 165 | 39% | −$14,504 | $14,831 | 0.36 | ❌ broken |
| bt_qqq_2021 / exit_baseline | 2021 | 2× | 220 | 67% | −$647 | $4,273 | 0.96 | ❌ broken |
| bt_qqq_2021h1 | 2021 H1 | 2× | 111 | 73% | +$2,558 | $1,805 | 1.39 | ❌ broken |
| exit_nostop / letrun / tohold | 2021 | none | 193 | 99.5% | **+$21,313** | $9 | 2369 | ❌ broken² |
| bt_qqq_2020 | 2020 | 2× | 16 | 6% | −$3,836 | $3,836 | 0.01 | ❌ broken |
| nostop_2020 | 2020 | none | 7 | 14% | −$1,080 | $1,138 | 0.05 | ❌ broken |

¹ **"fixed"** had the bounded-debit math but **not** slippage / daily-exit-cadence, so it
still cherry-picked exits → fake +$12,983.

³ **"realistic"** was the first cost-realistic run, but it predates the #104 fake-win fix, so
its −$42 is inflated ~30× by fabricated `profit_target` wins. The **`_clean` rows above
supersede it** (same config, fixed engine) → the true 2022 figure is **−$1,216**.

² **The smoking gun.** These three 2021 runs used profit targets of **0.8, 0.5, and 0.9**
and produced the *identical* result: **+$21,313, 99.48% win, $9 max drawdown.** A profit
target that doesn't change the outcome is impossible — it proves the old engine exited at
the single most favorable intraday minute regardless of the rule. **Ignore every ❌ row.**

---

## 2. The strategy — intraday iron condor (exact rules)

**Instrument:** QQQ options (SPY backfilling). 1-minute quote data from ThetaData.
Contract multiplier = 100.

**Entry — once per day at 09:45 ET, max 1 position open at a time:**
- **Short strikes:** ~**16-delta** put and call (`target_delta = 0.16`, tolerance `±0.08`).
  Delta is *estimated* via Black-Scholes from quotes, because ThetaData VALUE tier has no
  historical Greeks. *(Alternative "premium" mode: pick shorts whose bid ≈ $1.00.)*
- **Long wings:** **$5** beyond each short (`wing_width = 5`) → **defined risk**.
- **Expiry window:** **30–45 DTE** at entry (`min_dte = 30`, `max_dte = 45`).
- **Entry filter:** reject if `credit < max(min_credit, 10% × wing)` — kills degenerate
  "$0.09 credit" quote-artifact condors.

**Structure (4 legs):**
```
sell short put  Kp_s   +   buy long put  Kp_l = Kp_s − 5      (put spread)
sell short call Kc_s   +   buy long call Kc_l = Kc_s + 5      (call spread)
```
You **collect a credit** up front and profit if QQQ stays between the short strikes.
It's a **short-volatility / range-bound** bet with capped risk and capped reward.

**Exit — checked at each mark; in the realistic engine, profit-target/stop can only act at
the once-a-day 15:55 ET "decision point":**
- **profit_target:** `debit ≤ credit × (1 − 0.50)` → buy back at 50% of max profit
- **stop_loss:** `debit ≥ credit × stop_mult` (2× normally; "no-stop" = 99×)
- **time_exit:** `DTE ≤ 21` (forced roll)
- **expiration:** `DTE ≤ 0`

---

## 3. The math (exact formulas in the engine)

**Entry credit** (sell at bid, buy at ask — conservative):
```
credit = short_put.bid + short_call.bid − long_put.ask − long_call.ask
```
**Risk bounds:**
```
wing      = short_put.strike − long_put.strike   (= long_call.strike − short_call.strike) = 5
max_loss  = wing − credit
max_profit = credit
```
**Close debit** (cost to buy the condor back) — this is where the 6 fixes live:
```
quote_debit = short_put.ask + short_call.ask − long_put.bid − long_call.bid     (raw, unreliable)

# intrinsic value from the reliable, dense underlying price S:
put_spread  = clamp(short_put.strike − S, 0, wing)
call_spread = clamp(S − short_call.strike, 0, wing)
intrinsic   = put_spread + call_spread        # only one side can be ITM, so intrinsic ≤ wing

# the trustworthy debit: floored at intrinsic (kills fake wins),
# capped at wing (kills impossible losses):
debit = clamp(quote_debit, intrinsic, wing)
debit = min(debit + slippage × 4, wing)       # exit slippage on the 4 legs
# (if leg quotes are missing entirely, settle = clamp(intrinsic, 0, wing))
```
**P&L per trade** (× 100 multiplier):
```
gross = (credit − debit) × 100
net   = gross − commission − entry_slippage
        commission     = 0.65 / contract × 4 legs × 2 (open+close) = $5.20
        entry_slippage = 0.02 / contract × 4 legs × 100            = $8.00
        (exit slippage is already inside `debit` above)
```
**Key property:** net P&L is now **bounded** to
`[ −(max_loss × 100 + friction),  +(max_profit × 100 − friction) ]`.
It can never exceed the $5 wing in either direction — exactly the defined-risk reality the
old engine violated.

**Win-rate sanity check:** a 16-delta short strike is ITM ~16% of the time, so a condor's
theoretical win rate ≈ `1 − 2 × 0.16 = 68%`. The realistic 2022 run produced **exactly
68%** — the strongest evidence the engine is now honest.

---

## 4. Why the old numbers were garbage (history, so it doesn't repeat)

The old engine had two fatal flaws:

1. **Unbounded marking.** It valued the condor from sparse/stale option quotes. On illiquid
   deep-ITM legs this produced a close debit of **$9.85 on a $5-wide spread** — a loss of
   **−$976** on a position whose max loss is **$491**. Impossible.
2. **Exit cherry-picking with perfect fills.** It checked the profit target every single
   minute and exited at the *first favorable mark* with a zero-slippage fill. Over ~11 days
   of minute bars, almost any position momentarily marks favorably, so it banked wins on
   positions that were actually deep underwater (one trade was **−$471 at its worst** and
   still exited **+$40**).

The six fixes (merged in PR #101):
1. **Defined-risk cap** — debit ≤ wing.
2. **Intrinsic settlement** — floor debit at intrinsic from the underlying; settle even when
   quotes are missing.
3. **Reject degenerate entries** — credit ≥ 10% of wing.
4. **Commissions** — $0.65/contract round trip.
5. **Slippage** — $0.02/contract/leg, entry and exit.
6. **Daily exit cadence** — act on profit-target/stop once a day (15:55), not the best minute.

Result on the QQQ-2022 no-stop gate: **+$11,349 / 95.5% (fake) → −$42 / 68% (real).**
A no-stop condor held through a −34% bear year is correctly a small net loser.

---

## 5. What's next

- **Cross-regime suite (2020 / 2021 / 2022) — DONE** (the ✅ rows). This config loses in every
  regime. The old per-year numbers are void.
- **The decision this forces:** since even the ideal regime (calm 2021) loses, the next step is
  an **expectancy-ranked parameter sweep** — vary delta / DTE / wing width / profit-target /
  hold-to-expiration vs 21-DTE exit — to learn whether *any* condor configuration has positive
  per-trade expectancy. If the sweep finds nothing, the iron-condor approach is a **pass** and
  we pivot. (Note: the current sweep ranks on win-rate / total-P&L, which is the win-rate trap;
  it must rank on **expectancy** first — see the engine audit, finding A4.)
- **Gauntlet for any positive result the sweep finds:** cost-realism (done) → out-of-sample
  lock → walk-forward persistence → deflated Sharpe. Only a result that survives all four is real.
- **Reference for the rest of the project:** (a) trust **only** the ✅ `_clean` rows, (b) the
  strategy/math above is the shared reference. This options work is the project's spine.

*All raw reports live in `research/*.md`. The engine code is `src/trader/options/intraday.py`
(marking/exits) and `src/trader/options/iron_condor.py` (construction + the bounded-debit math).*
