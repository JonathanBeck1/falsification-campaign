# Campaign Scoreboard — master results table

Auto-generated from `brain/34_master_test_registry.md` by `scripts/build_campaign_scoreboard.py`. Do not edit by hand — re-run the generator. This is the research paper's main results table.

## Tally

| metric | count |
|---|---:|
| Total tests in registry | 51 |
| **Tested (verdict reached)** | **40** |
| &nbsp;&nbsp;— Kills | 27 |
| &nbsp;&nbsp;— No-edge | 8 |
| &nbsp;&nbsp;— Marginal / split | 3 |
| &nbsp;&nbsp;— Data-wall | 2 |
| In-flight | 2 |
| Planned | 8 |
| Merged / folded | 1 |

**Headline:** 37/40 tested strategies reached a negative verdict (kill / no-edge / data-wall); 3 marginal (alive but not claimable). 2 in-flight, 8 planned.

## By category

| category | tested | kills | no-edge | marginal | data-wall | in-flight | planned |
|---|---:|---:|---:|---:|---:|---:|---:|
| Index options / volatility | 5 | 1 | 4 | 0 | 0 | 0 | 0 |
| 0DTE / intraday options | 0 | 0 | 0 | 0 | 0 | 1 | 2 |
| Single-name equity options | 5 | 4 | 0 | 0 | 1 | 0 | 0 |
| Crypto | 5 | 4 | 0 | 1 | 0 | 0 | 0 |
| Futures | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| Equity events & structural flow | 11 | 9 | 1 | 0 | 1 | 0 | 1 |
| Catalyst / news | 2 | 2 | 0 | 0 | 0 | 0 | 1 |
| CEF / special situations | 3 | 1 | 0 | 2 | 0 | 1 | 0 |
| Cross-sectional / multi-asset / macro | 5 | 2 | 3 | 0 | 0 | 0 | 0 |
| Seasonality / calendar | 4 | 4 | 0 | 0 | 0 | 0 | 0 |

## Results

| id | category | name | verdict | result |
|---|---|---|---|---|
| T01 | Index options / volatility | Intraday iron-condor sweep (**SPY**, 5-day early-lab plumbing smoke —… | NO EDGE | no edge |
| T02 | Index options / volatility | Iron-condor cross-regime | NO EDGE | no edge |
| T03 | Index options / volatility | QQQ option features (GEX, vol-of-vol, 25Δ skew, term) | NO EDGE | no edge |
| T04 | Cross-sectional / multi-asset / macro | Cross-sectional pairs / RV | KILL | KILL (SPY/IVV microstructure) |
| T05 | Cross-sectional / multi-asset / macro | Multi-asset regime signals | NO EDGE | no edge |
| T06 | Cross-sectional / multi-asset / macro | Intraday QQQ strategies | KILL | DATA KILL (parity-derived) |
| T07 | Equity events & structural flow | PEAD | KILL | LOOK-AHEAD KILL |
| T08 | Equity events & structural flow | 8-K item-type study | NO EDGE | no edge |
| T09 | Index options / volatility | QQQ options microstructure (spread/depth/large quotes) | NO EDGE | no edge |
| T10 | Cross-sectional / multi-asset / macro | Small / illiquid universes | NO EDGE | no edge |
| T11 | Cross-sectional / multi-asset / macro | Pre-2010 SPY OOS | NO EDGE | no edge |
| T12 | Equity events & structural flow | IPO lock-up expiry | KILL | KILL (decayed) |
| T13 | CEF / special situations | CEF activist follow (Saba 13D) | MARGINAL | MARGINAL FAIL |
| T14 | Equity events & structural flow | SPAC trust arb | KILL | KILL (below T-bills) |
| T15 | CEF / special situations | CEF broad discount tilt | MARGINAL | bounded, uncapturable |
| T16 | CEF / special situations | CEF survival backtest | KILL | KILL (data glitch) |
| T17 | Catalyst / news | News catalog Phase 2 (27 cohorts) | KILL | 4 baseline artifacts |
| T18 | Catalyst / news | product_news matched-control | KILL | KILL (composition) |
| T19 | Index options / volatility | VRP daily iron condor (signed pre-reg) | KILL | KILL, mechanism null |
| T20 | 0DTE / intraday options | 0DTE short-premium (defined-risk, mechanical) | IN-FLIGHT | data backfilling |
| T21 | CEF / special situations | CEF resolution-selection (matched control + NAV) | IN-FLIGHT | Phase 5, pending paid Tiingo decision |
| T22 | Single-name equity options | Index dispersion / correlation risk premium (QQQ vs 26 constituents) | KILL | real premium (implied ρ 0.38 > realized ρ 0.35; GROSS vega-neutral book t=+1.98, win 58%) but the 26 single-name straddle round-trips at realized quoted half-s… |
| T23 | Single-name equity options | Single-name earnings IV crush | KILL | KILL: pre-earnings IV overstates the move (+1.59% crush gap) but the short straddle loses −0.59%/event (t=−3.61) after honest single-name bid/ask + tail; corr(… |
| T24 | Single-name equity options | Single-name vol term-structure carry | KILL | KILL: cross-sectional vega-neutral calendar ranked on the ≈30/≈90d ATM slope (26 names, N=53) loses after cost (−2.73/period, t=−3.41) and adds ZERO alpha over… |
| T25 | Single-name equity options | Single-name 25Δ skew dynamics | KILL | KILL: skew real & large (median +3.37 vol-pts, +90.7% of days) but signal-null — tertile long–short net −0.05%/wk t=−0.10, IS +0.12% → OOS SIGN-FLIP −0.24%, pl… |
| T26 | Single-name equity options | Hard-to-borrow / put-call-parity | DATA WALL | DATA_WALL: easy-to-borrow mega-caps → implied carry q |
| T27 | 0DTE / intraday options | 0DTE dealer-gamma-conditioned intraday reversion | PLANNED | Mech: retail 0DTE flow lopsided; gamma sign predicts intraday mean-revert vs trend. |
| T28 | 0DTE / intraday options | Opening vol-crush / intraday vol-of-vol | PLANNED | Mech: systematic AM IV decay. |
| T29 | Crypto | Perp funding carry, cross-sectional alt tail | KILL | KILL: after-cost −2.6%/yr (t=−0.05), IS +18bps/day → OOS −19bps/day flip. Funding +31.6%/yr gross is real but ~81% paid back by the short-perp price leg (−25.7… |
| T30 | Crypto | Spot-perp basis | MERGED | MERGED into T29 (no-padding): perp basis ≈ funding, the same cash-and-carry trade; not double-counted. |
| T31 | Crypto | Cross-exchange perp funding dispersion (Binance vs OKX) | KILL | KILL (friction-scale noise): real & sign-stable gross dispersion 0.58 bps/8h (t=51, all 19 symbols) but ≪ 20 bps two-venue round trip → after-cost −0.38 bps/in… |
| T32 | Crypto | Crypto VRP (Deribit DVOL) | MARGINAL | SPLIT/MARGINAL, the campaign's most-alive result. BTC: mechanism is REAL (corr +0.18, monotone quartiles — unlike the mechanism-null equity VRP at 0.01), survi… |
| T33 | Crypto | Crypto time-series momentum / trend-following | KILL | KILL: levered/timed BETA, not alpha. N=90 long-flat net +79.8%/yr but Sharpe 0.79 < buy-and-hold BTC 0.99 (−93% vs −77% DD); random-timing placebo w/ matched e… |
| T34 | Crypto | Stablecoin depeg mean-reversion | KILL | KILL (survivorship/tail trap): survivor-only +3.1% (t=3.74, 100% win) flips to −16.0% once UST's −67.6% death is in the sample; drop-worst flips sign; N=4. Tex… |
| T35 | Futures | Commodity roll yield / carry | PLANNED | Mech: long-only ETF holders pay roll. |
| T36 | Futures | Commodity seasonality (ag / energy) | PLANNED | Mech: weather/harvest calendar. |
| T37 | Futures | Futures term-structure / backwardation signal | PLANNED |  |
| T38 | Futures | COT positioning signal | PLANNED | Mech: commercial vs spec imbalance. |
| T39 | Equity events & structural flow | Index reconstitution / "index effect" (S&P add/delete, announce→effec… | KILL | KILL: decayed null (add CAR +0.48% gross/+0.38% net, t=1.11, median<0) AND placebo-absorbed (same-name random windows +0.41%, t=2.85 → name drift not flow). De… |
| T40 | Equity events & structural flow | Cash-merger arb spread | DATA WALL | DATA_WALL: completed-deal targets delist on close and yfinance PURGES them — 2/24 completed priceable (~100% true purge), vs broken survivors (NXPI −11.8%/yr)… |
| T41 | Equity events & structural flow | Buyback-announcement drift (8-K Item 8.01) | KILL | KILL (friction-scale #2): broad cohort PASSES the full gate (after-cost +1.08%, t=+3.39, N=1303) but is a small-cap illiquidity mirage — 64% sub-$10M/day. Load… |
| T42 | Equity events & structural flow | Spin-off post-event drift (Form 10-12B, forced index-fund selling) | KILL | KILL: decayed null. Spinco 1-mo CAR −0.07% gross/−0.27% net, t=−0.03, N=104 (survivorship-safe, incl. AFIIQ/BXRXQ bankruptcies); IS −0.22%/OOS +0.05% sign-unst… |
| T43 | Equity events & structural flow | Earnings-announcement premium | KILL | real but KILL: gross +0.34%/after-cost +0.24% (t=1.85, <2); IS +0.46% (t=2.76) → OOS −0.01% (t=−0.07) decay; corr(premium, window-vol)=+0.73 → compensated jump… |
| T44 | Equity events & structural flow | Insider cluster buying (Form 4, ≥2 insiders/30d) | KILL | KILL: forward market-adj CAR is NEGATIVE — gross −1.46%/after-cost −1.86% (t=−0.83) at 3m; IS +0.34% → OOS −3.82% sign-FLIP; same-name placebo also −4.87% (the… |
| T45 | Equity events & structural flow | 13F institutional cloning (filing-date) | KILL | KILL: cloning 12 famous managers' NEW positions from the FILING date earns after-cost −0.56% at 3m (t=−2.09, wrong sign), LOSES to same-name placebo (+0.33%),… |
| T46 | Equity events & structural flow | High-short-interest / squeeze signal | PLANNED | Mech: forced covering. |
| T47 | Seasonality / calendar | FOMC pre-announcement drift (Lucca–Moench) | KILL | KILL (decayed: IS t=2.08 → OOS t=−0.02; pooled t=1.35 sits inside the placebo \|t\| band). |
| T48 | Seasonality / calendar | Turn-of-month effect | KILL | KILL: +3.4 bps/day gross (t=1.05, below placebo 1.93); IS +5.8 bps (t=1.21) → OOS +0.8 bps (t=0.18) — decayed seasonal, in-noise. |
| T49 | Seasonality / calendar | Sell-in-May / Halloween indicator | KILL | KILL: winter−summer +0.48%/mo but t=1.12 (noise); seasonal Sharpe 0.68 < buy-and-hold 0.77 — lower drawdown is exposure reduction (50% in cash), NOT alpha. Exp… |
| T50 | Seasonality / calendar | Day-of-week / pre-holiday effects | KILL | KILL both: Monday effect gone & sign-reversed (+0.054%/day, t=0.22); pre-holiday +5.3bps gross but t=0.93 < placebo 1.94, cost-eaten. Decayed + friction-scale… |
| T51 | Catalyst / news | LLM news-interpretation predictive test | PLANNED | Mech: reasoning-model interpretation on names the fast money ignores; the only "news" angle not already dead. Low prior; hindsight-leak risk severe. |

