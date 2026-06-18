"""LeaderboardRow + build_leaderboard orchestrator.

Reads `brain_equity_curve` and `orders` from the store, computes metrics
via `scoring/metrics.py`, returns sorted `LeaderboardRow` list. Pure
read-only — no writes, no LLM, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from trader.scoring.deflated_sharpe import deflated_sharpe_value
from trader.scoring.metrics import (
    annualized_return,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe_ratio,
    total_return,
)
from trader.storage.store import Store

ConfidenceTier = Literal[
    "insufficient", "early_read", "directional", "useful", "m4_grade"
]


@dataclass(frozen=True)
class LeaderboardRow:
    brain: str
    days: int
    total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    hit_rate: float
    trade_count: int
    vs_buy_and_hold_pp: float
    composite_score: float
    deflated_sharpe: float
    deflated_composite: float
    confidence_tier: ConfidenceTier


def confidence_tier_for_days(days: int) -> ConfidenceTier:
    """Bucket day-count into the spec's confidence tiers.

    <5 → insufficient · 5-19 → early_read · 20-29 → directional ·
    30-99 → useful · >=100 → m4_grade.
    """
    if days < 5:
        return "insufficient"
    if days < 20:
        return "early_read"
    if days < 30:
        return "directional"
    if days < 100:
        return "useful"
    return "m4_grade"


def _drawdown_penalty(max_dd: float) -> float:
    """Fraction by which a max drawdown discounts the (deflated) Sharpe in the
    composite score. A **20% drawdown halves** the Sharpe and a **40%+ drawdown
    zeroes** it -- so the multiplier is 2.5 (0.20*2.5 = 0.5, 0.40*2.5 = 1.0):

        penalty = min(1.0, |max_dd| * 2.5)

    (Previously this used *5.0, which zeroed the score at a 20% drawdown -- twice
    as harsh as the documented intent and over-penalizing normal strategies. The
    composite is the primary leaderboard sort key, so this materially changes
    rankings.)
    """
    return min(1.0, abs(max_dd) * 2.5)


def _composite_score(sharpe: float, max_dd: float) -> float:
    return sharpe * max(0.0, 1.0 - _drawdown_penalty(max_dd))


def _deflated_composite_score(deflated_sharpe: float, max_dd: float) -> float:
    """Same drawdown penalty as the raw composite, applied to the
    selection-adjusted SR point estimate."""
    return deflated_sharpe * max(0.0, 1.0 - _drawdown_penalty(max_dd))


def _coerce_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _parsed_equity_curve(
    store: Store, brain: str
) -> list[tuple[date, float]]:
    """Pull raw rows from the store and coerce to (date, float) tuples
    sorted ascending."""
    rows = store.get_equity_curve(brain)
    curve: list[tuple[date, float]] = []
    for row in rows:
        try:
            curve.append((_coerce_date(row["trade_date"]), float(row["equity"])))
        except (KeyError, ValueError, TypeError):
            continue
    curve.sort(key=lambda item: item[0])
    return curve


def _filter_curve(
    curve: list[tuple[date, float]],
    *,
    since: date | None,
    until: date | None,
) -> list[tuple[date, float]]:
    if since is None and until is None:
        return curve
    out: list[tuple[date, float]] = []
    for d, eq in curve:
        if since is not None and d < since:
            continue
        if until is not None and d > until:
            continue
        out.append((d, eq))
    return out


def _trade_count_for_brain(
    store: Store, brain: str, *, since: date | None, until: date | None
) -> int:
    """Count orders submitted by this brain within the optional date window.

    Uses `submitted_at` text which is ISO-ish (`YYYY-MM-DD HH:MM:SS` or
    `YYYY-MM-DDTHH:MM:SS+00:00`). String comparison is fine for both forms
    because they share the lexicographic prefix.
    """
    clauses = ["brain = ?"]
    params: list[object] = [brain]
    if since is not None:
        clauses.append("submitted_at >= ?")
        params.append(since.isoformat())
    if until is not None:
        clauses.append("submitted_at < ?")
        # exclusive upper bound at start of (until + 1 day) — using until ISO
        # plus 'T23:59:59' keeps it inclusive of trades on the until date.
        params.append(f"{until.isoformat()}T23:59:59.999")
    where = " AND ".join(clauses)
    sql = f"SELECT COUNT(*) AS n FROM orders WHERE {where}"
    with store._conn() as c:
        row = c.execute(sql, params).fetchone()
        return int(row["n"]) if row else 0


def _list_brains_with_equity(store: Store) -> list[str]:
    with store._conn() as c:
        rows = c.execute(
            "SELECT DISTINCT brain FROM brain_equity_curve ORDER BY brain"
        ).fetchall()
        return [str(r["brain"]) for r in rows]


def build_leaderboard(
    store: Store,
    *,
    since: date | None = None,
    until: date | None = None,
    oos_cutoff: date | None = None,
    baseline_brain: str = "BuyAndHoldBrain",
) -> list[LeaderboardRow]:
    """Build sorted leaderboard rows from the store's equity-curve data.

    - Enumerates brains with equity rows in `brain_equity_curve`.
    - Filters each curve to `[since, until]` (both inclusive bounds on
      `trade_date`).
    - Computes metrics + confidence_tier per brain.
    - `vs_buy_and_hold_pp = brain.total_return - baseline.total_return`
      in percentage points. If baseline has insufficient data (or is
      missing entirely), `vs_buy_and_hold_pp` is 0.0.
    - Sort: deflated_composite DESC for tiers != insufficient; insufficient
      rows pinned to the bottom. Raw `composite_score` is retained per row
      for diagnostic visibility.

    Deflation: the Bailey-LdP DSR adjustment (see
    `trader.scoring.deflated_sharpe`) is applied per variant. ``n_trials``
    equals the number of brains enumerated in this call; ``n_observations``
    per variant is the row count of daily returns in the trading-days
    window for that variant. The default sort key is
    ``deflated_composite = deflated_sharpe * max(0, 1 - 5·|maxDD|)``.

    Locked OOS protocol — `oos_cutoff`: when set, rows on or after that
    date are excluded from BOTH the baseline curve and each variant's
    curve, so the multi-variant ranking only sees pre-cutoff (in-sample)
    data. This complements the `leaderboard-oos` CLI, which is the only
    way to score a variant against the post-cutoff window.
    """
    effective_until = until
    if oos_cutoff is not None:
        oos_until = oos_cutoff - timedelta(days=1)
        effective_until = (
            oos_until if effective_until is None else min(effective_until, oos_until)
        )

    baseline_curve = _filter_curve(
        _parsed_equity_curve(store, baseline_brain), since=since, until=effective_until
    )
    baseline_total = total_return(baseline_curve) if len(baseline_curve) >= 2 else None

    brains = _list_brains_with_equity(store)
    n_trials = len(brains)

    rows: list[LeaderboardRow] = []
    for brain in brains:
        curve = _filter_curve(
            _parsed_equity_curve(store, brain), since=since, until=effective_until
        )
        days = len(curve)
        rets = daily_returns(curve)
        ret = total_return(curve)
        ann = annualized_return(curve)
        sharpe = sharpe_ratio(rets)
        mdd = max_drawdown(curve)
        hr = hit_rate(rets)
        tcount = _trade_count_for_brain(store, brain, since=since, until=effective_until)
        vs_bh = (ret - baseline_total) * 100.0 if baseline_total is not None else 0.0
        tier = confidence_tier_for_days(days)
        n_obs = len(rets)
        dsr_value = deflated_sharpe_value(
            sharpe, n_trials=n_trials, n_observations=n_obs
        )
        rows.append(
            LeaderboardRow(
                brain=brain,
                days=days,
                total_return=ret,
                annualized_return=ann,
                sharpe=sharpe,
                max_drawdown=mdd,
                hit_rate=hr,
                trade_count=tcount,
                vs_buy_and_hold_pp=vs_bh,
                composite_score=_composite_score(sharpe, mdd),
                deflated_sharpe=dsr_value,
                deflated_composite=_deflated_composite_score(dsr_value, mdd),
                confidence_tier=tier,
            )
        )

    # Sort: insufficient rows last, otherwise deflated_composite DESC,
    # tie-broken by raw composite_score DESC, then total_return DESC, then
    # brain name asc for stability.
    rows.sort(
        key=lambda r: (
            r.confidence_tier == "insufficient",
            -r.deflated_composite,
            -r.composite_score,
            -r.total_return,
            r.brain,
        )
    )
    return rows


def build_oos_row(
    store: Store,
    *,
    variant: str,
    since: date,
) -> LeaderboardRow:
    """Score a SINGLE variant on the OOS window (`since` onward, inclusive).

    Locked OOS protocol: this is the only programmatic surface that
    scores a variant against post-cutoff out-of-sample data, and it
    deliberately accepts exactly one variant name so that no caller can
    use it to rank multiple variants on OOS data. The `trader
    leaderboard-oos` CLI command is the only intended caller.

    Returns a `LeaderboardRow` populated from the variant's equity curve
    restricted to `trade_date >= since`. If fewer than 5 OOS days are
    available the row's `confidence_tier` is `'insufficient'`; callers
    should report this as `insufficient_oos` rather than presenting the
    metrics as a Sharpe / composite.
    """
    curve = _filter_curve(
        _parsed_equity_curve(store, variant), since=since, until=None
    )
    days = len(curve)
    rets = daily_returns(curve)
    ret = total_return(curve)
    ann = annualized_return(curve)
    sharpe = sharpe_ratio(rets)
    mdd = max_drawdown(curve)
    hr = hit_rate(rets)
    tcount = _trade_count_for_brain(store, variant, since=since, until=None)
    # Single-variant OOS scoring: no multiple-testing selection here, so
    # n_trials=1 (minimal deflation); n_observations is the OOS return count.
    dsr_value = deflated_sharpe_value(sharpe, n_trials=1, n_observations=len(rets))
    return LeaderboardRow(
        brain=variant,
        days=days,
        total_return=ret,
        annualized_return=ann,
        sharpe=sharpe,
        max_drawdown=mdd,
        hit_rate=hr,
        trade_count=tcount,
        vs_buy_and_hold_pp=0.0,
        composite_score=_composite_score(sharpe, mdd),
        deflated_sharpe=dsr_value,
        deflated_composite=_deflated_composite_score(dsr_value, mdd),
        confidence_tier=confidence_tier_for_days(days),
    )
