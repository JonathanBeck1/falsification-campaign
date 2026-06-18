#!/usr/bin/env python
"""Run the pre-registered T23 single-name earnings IV-crush study (end-to-end).

Pre-registration: research/earnings_iv_crush_preregistration.md. Falsify-first.

Free, owned data only: the EOD option-chain parquet lake at
``$TRADER_EOD_LAKE_ROOT`` (ThetaData-collected)
plus yfinance scheduled earnings dates. Spot is anchored from the chain itself
via put-call parity (see pre-reg sec.3 — the foundation's yfinance spot is
split-mismatched against the lake's unadjusted strikes). The pure core lives in
``trader.catalysts.earnings_iv_crush`` and is unit-tested without I/O.

The placebo: the same "sell front straddle at close, buy back next session" round
trip run on randomly sampled NON-earnings trade-date pairs of the same names.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.earnings_iv_crush import (  # noqa: E402
    COMMISSION_PER_STRADDLE,
    MIN_FRONT_DAYS,
    CrushEvent,
    aggregate,
    compute_crush_event,
    evaluate_gate,
    is_amc,
    mean,
    median,
    pearson,
    std,
    t_stat_one_sample,
    tail_report,
    welch_t,
)
from trader.catalysts.vol_surface_data import LAKE_ROOT  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(30))
log = structlog.get_logger()

# --- Pre-registered universe (24 fully-collected single names; EXCLUDES the
# still-collecting AAPL/AMZN/NVDA and the QQQ/SPY index ETFs). See pre-reg sec.3.
UNIVERSE = [
    "ADBE", "AMAT", "AMD", "AVGO", "BKNG", "COST", "CSCO", "GOOG", "GOOGL",
    "HON", "INTU", "ISRG", "LIN", "LRCX", "META", "MU", "NFLX", "PEP", "QCOM",
    "REGN", "TMUS", "TSLA", "TXN", "VRTX",
]

SINCE = date(2022, 1, 1)
UNTIL = date(2026, 6, 15)
OOS_SPLIT_YEAR = 2023  # IS: earnings year <= 2023 ; OOS: >= 2024
N_PLACEBO_PER_TICKER = 30  # non-earnings pairs sampled per ticker
PLACEBO_GAP_DAYS = 7  # placebo anchors must be >= this many trade-days from any earnings
SEED = 23

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "earnings_iv_crush_report.md"
RESULTS_PATH = ROOT / "data" / "earnings_iv_crush_results.txt"
JSON_PATH = OUT_DIR / "earnings_iv_crush_study.json"


# --------------------------------------------------------------------------- #
# lake access (per-day chain shards)
# --------------------------------------------------------------------------- #
def lake_trade_dates(ticker: str) -> list[date]:
    """Sorted list of trade dates present in the lake for ``ticker`` in span."""

    root = LAKE_ROOT / f"root={ticker}"
    if not root.is_dir():
        return []
    out: list[date] = []
    for ydir in sorted(root.glob("trade_year=*")):
        for path in ydir.glob(f"{ticker}_*.parquet"):
            try:
                d = datetime.strptime(path.stem[len(ticker) + 1 :], "%Y-%m-%d").date()
            except ValueError:
                continue
            if SINCE <= d <= UNTIL:
                out.append(d)
    return sorted(out)


def read_chain(ticker: str, trade_date: date) -> pd.DataFrame:
    """Read one per-day chain shard (raw bid/ask/strike/right/expiration). Empty if missing."""

    path = (
        LAKE_ROOT
        / f"root={ticker}"
        / f"trade_year={trade_date.year}"
        / f"{ticker}_{trade_date.isoformat()}.parquet"
    )
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as exc:  # pragma: no cover
        log.warning("chain_read_failed", path=str(path), error=str(exc))
        return pd.DataFrame()


def prev_and_next(trade_dates: list[date], pivot: date, *, amc: bool) -> tuple[date, date] | None:
    """(entry_date, exit_date) lake trade-days bracketing the pricing session.

    AMC: priced next session -> entry = last trade-day <= pivot, exit = first
    trade-day strictly after entry.
    BMO: priced same session (pivot) -> entry = last trade-day strictly before
    pivot, exit = first trade-day on/after pivot.
    """

    if not trade_dates:
        return None
    if amc:
        before = [d for d in trade_dates if d <= pivot]
        if not before:
            return None
        entry = before[-1]
    else:
        before = [d for d in trade_dates if d < pivot]
        if not before:
            return None
        entry = before[-1]
    after = [d for d in trade_dates if d > entry]
    if not after:
        return None
    return entry, after[0]


# --------------------------------------------------------------------------- #
# earnings dates
# --------------------------------------------------------------------------- #
def fetch_earnings(ticker: str) -> list[tuple[date, bool]]:
    """[(earnings_date, amc?), ...] in span from yfinance. AMC from ET hour."""

    import yfinance as yf

    try:
        frame = yf.Ticker(ticker).get_earnings_dates(limit=100)
    except Exception as exc:  # pragma: no cover
        log.warning("earn_dates_failed", ticker=ticker, error=str(exc))
        return []
    if frame is None or frame.empty:
        return []
    today = date.today()
    seen: dict[date, bool] = {}
    for ts in frame.index:
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        et = stamp.tz_convert("US/Eastern")
        d = et.date()
        if not (SINCE <= d <= UNTIL) or d >= today:
            continue
        hour = None if (et.hour == 0 and et.minute == 0) else et.hour
        seen[d] = is_amc(hour)
    return sorted(seen.items())


# --------------------------------------------------------------------------- #
# event + placebo builders
# --------------------------------------------------------------------------- #
def build_events(ticker: str, trade_dates: list[date]) -> tuple[list[CrushEvent], int]:
    """Earnings short-straddle events for one ticker; returns (events, n_dropped)."""

    events: list[CrushEvent] = []
    dropped = 0
    for ann_date, amc in fetch_earnings(ticker):
        bracket = prev_and_next(trade_dates, ann_date, amc=amc)
        if bracket is None:
            dropped += 1
            continue
        entry_date, exit_date = bracket
        entry_chain = read_chain(ticker, entry_date)
        exit_chain = read_chain(ticker, exit_date)
        ev = compute_crush_event(
            ticker=ticker,
            earnings_date=ann_date,
            entry_chain=entry_chain,
            exit_chain=exit_chain,
            entry_date=entry_date,
            exit_date=exit_date,
        )
        if ev is None:
            dropped += 1
            continue
        events.append(ev)
    return events, dropped


def build_placebo(
    ticker: str,
    trade_dates: list[date],
    earnings_dates: list[date],
    *,
    rng: random.Random,
    n_samples: int,
) -> list[float]:
    """Non-earnings one-day short-straddle returns (the placebo carry).

    Anchors are trade-days at least ``PLACEBO_GAP_DAYS`` index-positions from any
    earnings entry; the round trip uses consecutive lake trade-days.
    """

    if len(trade_dates) < 2:
        return []
    pos = {d: i for i, d in enumerate(trade_dates)}
    blocked: set[int] = set()
    for ed in earnings_dates:
        # block the index window around the earnings entry day (nearest <= ed)
        before = [d for d in trade_dates if d <= ed]
        if not before:
            continue
        i = pos[before[-1]]
        for j in range(i - PLACEBO_GAP_DAYS, i + PLACEBO_GAP_DAYS + 1):
            blocked.add(j)
    candidates = [i for i in range(len(trade_dates) - 1) if i not in blocked]
    rng.shuffle(candidates)
    out: list[float] = []
    for i in candidates:
        if len(out) >= n_samples:
            break
        entry_date = trade_dates[i]
        exit_date = trade_dates[i + 1]
        entry_chain = read_chain(ticker, entry_date)
        exit_chain = read_chain(ticker, exit_date)
        ev = compute_crush_event(
            ticker=ticker,
            earnings_date=entry_date,  # label only
            entry_chain=entry_chain,
            exit_chain=exit_chain,
            entry_date=entry_date,
            exit_date=exit_date,
        )
        if ev is not None:
            out.append(ev.after_cost_return)
    return out


# --------------------------------------------------------------------------- #
def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    all_events: list[CrushEvent] = []
    placebo_returns: list[float] = []
    warnings: list[str] = []
    total_dropped = 0
    used_tickers = 0

    for ticker in UNIVERSE:
        tds = lake_trade_dates(ticker)
        if len(tds) < 50:
            warnings.append(f"{ticker}: only {len(tds)} lake trade-days (skipped)")
            continue
        events, dropped = build_events(ticker, tds)
        total_dropped += dropped
        if not events:
            warnings.append(f"{ticker}: no complete earnings straddle events")
            continue
        used_tickers += 1
        all_events.extend(events)
        earn_dates = [e.earnings_date for e in events]
        placebo_returns.extend(
            build_placebo(ticker, tds, earn_dates, rng=rng, n_samples=N_PLACEBO_PER_TICKER)
        )
        log.info("ticker_done", ticker=ticker, events=len(events), dropped=dropped)

    # ----- PRIMARY: after-cost short-straddle return -----
    returns = [e.after_cost_return for e in all_events]
    stats = aggregate(returns, label="earnings")
    placebo_stats = aggregate(placebo_returns, label="placebo")

    earn_minus_placebo_t = welch_t(returns, placebo_returns)
    premium = stats.mean - placebo_stats.mean

    # IS / OOS split on earnings year.
    is_ret = [e.after_cost_return for e in all_events if e.earnings_date.year <= OOS_SPLIT_YEAR]
    oos_ret = [e.after_cost_return for e in all_events if e.earnings_date.year > OOS_SPLIT_YEAR]

    # implied-vs-realized decomposition (the IV-overstatement check).
    priced = [e.priced_move for e in all_events]
    realized = [e.realized_move for e in all_events]
    crush_gaps = [e.crush_gap for e in all_events]
    # corr(after-cost P&L, realized move): expected strongly negative (deaths = big moves).
    pnl_vs_move = pearson(returns, realized)

    tr = tail_report(all_events)

    gate = evaluate_gate(
        n_events=len(all_events),
        after_cost_mean=stats.mean,
        after_cost_t=stats.t_stat,
        is_mean=mean(is_ret),
        is_n=len(is_ret),
        oos_mean=mean(oos_ret),
        oos_n=len(oos_ret),
        placebo_mean=placebo_stats.mean,
        earnings_minus_placebo_t=earn_minus_placebo_t,
    )

    # top/bottom-5 contributor inspection (tripwire hygiene).
    ranked = sorted(all_events, key=lambda e: e.after_cost_return)
    bottom5 = ranked[:5]
    top5 = ranked[-5:][::-1]

    run_at = datetime.now(UTC).isoformat()
    warning_lines = [f"- {w}" for w in warnings] or ["- None"]

    lines = [
        "# T23 - Single-Name Earnings IV Crush Study Result",
        "",
        "Pre-registration: `research/earnings_iv_crush_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Span: {SINCE} .. {UNTIL}",
        f"- Universe: {len(UNIVERSE)} single names ({used_tickers} contributed events)",
        "  EXCLUDED AAPL/AMZN/NVDA (still collecting) and QQQ/SPY (indices).",
        f"- Trade: sell ATM front straddle (>= {MIN_FRONT_DAYS}d tenor) at pre-earnings",
        "  close, buy back at first post-earnings close. Spot anchored by put-call parity.",
        f"- Friction: cross the quoted bid/ask each leg + ${COMMISSION_PER_STRADDLE:.2f}/straddle commission.",
        f"- IS = earnings year <= {OOS_SPLIT_YEAR}, OOS = year > {OOS_SPLIT_YEAR}",
        "",
        "## Sample accounting",
        f"- Complete earnings straddle events: {len(all_events)}",
        f"- Events dropped (missing bracket/quote/glitch): {total_dropped}",
        f"- Placebo (non-earnings) one-day straddles: {len(placebo_returns)}",
        "",
        "## PRIMARY: after-cost short-straddle return (fraction of spot)",
        f"- N events: {stats.n}",
        f"- Mean: {stats.mean * 100:+.3f}% of spot",
        f"- After-cost t-stat: {stats.t_stat:+.2f}",
        f"- Median: {stats.median * 100:+.3f}%",
        f"- Win rate: {stats.win_rate * 100:.1f}%",
        f"- Sharpe (mean/std across events): {stats.sharpe:+.3f}",
        f"- Std across events: {std(returns) * 100:.3f}%",
        "",
        "## IV overstatement decomposition (priced vs realized move)",
        f"- Mean priced move (straddle mid / spot): {mean(priced) * 100:.3f}%",
        f"- Mean realized overnight move: {mean(realized) * 100:.3f}%",
        f"- Mean crush gap (priced - realized): {mean(crush_gaps) * 100:+.3f}%",
        f"- Median crush gap: {median(crush_gaps) * 100:+.3f}%",
        "  (positive => pre-earnings IV overstated the realized move on average)",
        "",
        "## Jump-variance check (is it compensated variance, not alpha?)",
        f"- Corr(after-cost P&L, realized move): {pnl_vs_move:+.3f}",
        "  (strongly negative => the losses ARE the big earnings gaps = compensated"
        " jump variance)",
        "",
        "## Same-name non-earnings placebo (the ordinary short-vol carry)",
        f"- N windows: {placebo_stats.n}",
        f"- Mean after-cost return: {placebo_stats.mean * 100:+.3f}%",
        f"- t-stat: {placebo_stats.t_stat:+.2f}",
        f"- Earnings premium over placebo: {premium * 100:+.3f}% (Welch t={earn_minus_placebo_t:+.2f})",
        "",
        "## IS / OOS (decay check)",
        f"- IS  (<= {OOS_SPLIT_YEAR}) mean: {mean(is_ret) * 100:+.3f}% "
        f"(n={len(is_ret)}, t={t_stat_one_sample(is_ret):+.2f})",
        f"- OOS (>  {OOS_SPLIT_YEAR}) mean: {mean(oos_ret) * 100:+.3f}% "
        f"(n={len(oos_ret)}, t={t_stat_one_sample(oos_ret):+.2f})",
        "",
        "## TAIL / loss distribution (catastrophic-tail report, MANDATORY)",
        f"- Worst single event: {tr.worst_return * 100:+.2f}% ({tr.worst_label})",
        f"- Loss events: {tr.n_losses}/{len(all_events)} ({tr.loss_share_of_n * 100:.1f}%)",
        f"- Sum of 5 worst events: {tr.top5_loss_sum * 100:+.2f}% of spot",
        f"- Sum of ALL events: {tr.gross_sum * 100:+.2f}% of spot",
        f"- Mean excluding 5 worst: {tr.mean_ex_worst5 * 100:+.3f}% "
        f"(vs full {stats.mean * 100:+.3f}%)",
        f"- Deaths dominate (full mean<=0 but positive ex-worst-5): {tr.deaths_dominate}",
        "- Bottom-5 (the deaths): "
        + ", ".join(f"{e.ticker} {e.earnings_date} {e.after_cost_return * 100:+.1f}%" for e in bottom5),
        "- Top-5 (the crush wins): "
        + ", ".join(f"{e.ticker} {e.earnings_date} {e.after_cost_return * 100:+.1f}%" for e in top5),
        "",
        "## Pre-registered gate verdict",
        f"### {'PASS' if gate.passed else 'FAIL'}",
        *[f"- {r}" for r in gate.reasons],
        "",
        "## Coverage warnings",
        *warning_lines,
        "",
    ]

    text = "\n".join(lines)
    try:
        REPORT_PATH.write_text(text)
        RESULTS_PATH.write_text(text)
        JSON_PATH.write_text(
            json.dumps(
                {
                    "run_at": run_at,
                    "n_events": len(all_events),
                    "n_placebo": len(placebo_returns),
                    "primary_mean": stats.mean,
                    "primary_t": stats.t_stat,
                    "primary_median": stats.median,
                    "win_rate": stats.win_rate,
                    "sharpe": stats.sharpe,
                    "mean_priced_move": mean(priced),
                    "mean_realized_move": mean(realized),
                    "mean_crush_gap": mean(crush_gaps),
                    "corr_pnl_realized_move": pnl_vs_move,
                    "placebo_mean": placebo_stats.mean,
                    "premium_over_placebo": premium,
                    "earnings_minus_placebo_t": earn_minus_placebo_t,
                    "is_mean": mean(is_ret),
                    "is_n": len(is_ret),
                    "oos_mean": mean(oos_ret),
                    "oos_n": len(oos_ret),
                    "tail_worst": tr.worst_return,
                    "tail_worst_label": tr.worst_label,
                    "tail_top5_loss_sum": tr.top5_loss_sum,
                    "tail_gross_sum": tr.gross_sum,
                    "tail_mean_ex_worst5": tr.mean_ex_worst5,
                    "deaths_dominate": tr.deaths_dominate,
                    "gate_passed": gate.passed,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"ERROR: could not write outputs: {exc}", file=sys.stderr)
        return 3

    print(text)
    print(f"Report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
