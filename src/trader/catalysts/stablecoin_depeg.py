"""T34 — stablecoin depeg mean-reversion (the survivorship/tail test).

Pre-registration: ``research/stablecoin_depeg_preregistration.md``.

The hypothesis under test is the **naive** rule: "buy a USD stablecoin when its
daily close first drops below $0.98, hold to a fixed horizon, collect the
re-peg." On *surviving* stablecoins (USDC dipped to ~$0.88 in Mar 2023 and
recovered) this looks like a free lunch. The whole point of T34 is that the
strategy's true return distribution is dominated by the rare **death spiral**:
TerraUST (UST) fell $1.00 -> ~$0 in May 2022. A "buy below $0.98" rule fires on
UST on the way to zero and loses ~100%.

So this module is built to make the deaths *un-droppable*:

* The event detector re-arms (one depeg = one event, not one per day below peg).
* The forward-return functions mark a still-open position to the **last
  available close** when the price series terminates — i.e. UST's archive ending
  at ~$0.18 books an ~80% realized loss instead of silently vanishing.
* :func:`survivorship_split` reports the mean WITH vs WITHOUT the dead coins —
  the headline number of the test.

Everything here is PURE (operates on in-memory pandas objects); the network
fetch lives in ``crypto_data`` and the orchestration in
``scripts/run_stablecoin_depeg_study.py``. No function here opens a socket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

# Pre-registered constants (fixed in the pre-reg; imported by the runner/tests).
DEPEG_THRESHOLD = 0.98  # close < this => depeg event
REARM_LEVEL = 0.995  # must recover to >= this to re-arm for a new event
HORIZON_DAYS = 30  # PRIMARY fixed-hold horizon (calendar days from t0)
PEG_TARGET = 0.995  # "recovered to peg" level for ret_to_peg
ROUND_TRIP_COST = 0.0020  # 20 bps round trip (pre-registered friction)
OOS_START = date(2023, 1, 1)  # IS: t0 < this ; OOS: t0 >= this


@dataclass(frozen=True)
class DepegEvent:
    """One depeg event and its pre-registered forward returns (GROSS).

    ``symbol`` / ``t0`` identify the event (first close < threshold after re-arm).
    ``entry`` is the t0 close (entry fill). ``terminal`` is True when the price
    series ended while the position was still open within the horizon — i.e. the
    coin died; ``exit_30d`` is then the last available close (a realized loss,
    NOT dropped). ``recovered`` is True iff close reached ``PEG_TARGET`` within
    the horizon.
    """

    symbol: str
    t0: date
    entry: float
    exit_7d: float
    exit_30d: float
    exit_to_peg: float
    ret_7d: float
    ret_30d: float
    ret_to_peg: float
    recovered: bool
    terminal: bool
    is_dead_coin: bool


def find_depeg_events(
    close: pd.Series,
    *,
    threshold: float = DEPEG_THRESHOLD,
    rearm_level: float = REARM_LEVEL,
) -> list[pd.Timestamp]:
    """PURE: dates of fresh depeg breaks in a daily close series.

    A break fires on the first close ``< threshold``; after firing the detector
    is **disarmed** until the close recovers to ``>= rearm_level`` (so a single
    multi-day depeg, e.g. a slow death, counts as ONE event — not one per day
    below peg, which would let one corpse manufacture dozens of overlapping
    "events"). The series is assumed ascending by date.
    """

    events: list[pd.Timestamp] = []
    armed = True
    for ts, px in close.items():
        if px != px:  # NaN guard
            continue
        if armed and px < threshold:
            events.append(ts)
            armed = False
        elif (not armed) and px >= rearm_level:
            armed = True
    return events


def _forward_exit(
    close: pd.Series, t0_pos: int, horizon_days: int
) -> tuple[float, bool]:
    """PURE: exit price ``horizon_days`` calendar days after t0, and terminal flag.

    Walks forward to the last bar whose date is within ``horizon_days`` of t0. If
    the series ENDS before that horizon is reached (the coin died), returns the
    last available close and ``terminal=True`` — this is how UST's death is
    realized as a loss instead of silently dropped.
    """

    t0 = close.index[t0_pos]
    deadline = t0 + pd.Timedelta(days=horizon_days)
    exit_pos = t0_pos
    for pos in range(t0_pos, len(close)):
        if close.index[pos] <= deadline:
            exit_pos = pos
        else:
            break
    # Terminal iff we never reached the deadline because the series ran out.
    terminal = close.index[exit_pos] < deadline and exit_pos == len(close) - 1
    return float(close.iloc[exit_pos]), terminal


def _forward_to_peg(
    close: pd.Series, t0_pos: int, horizon_days: int, peg_target: float
) -> float:
    """PURE: exit price for the "hold to re-peg, capped at horizon" rule.

    First close ``>= peg_target`` within the horizon -> that close. If never
    recovered within the horizon (UST never does), falls back to the same
    fixed-horizon exit as :func:`_forward_exit` (last close within horizon, or
    terminal last close) — so a coin that dies still books its realized loss.
    """

    t0 = close.index[t0_pos]
    deadline = t0 + pd.Timedelta(days=horizon_days)
    for pos in range(t0_pos + 1, len(close)):
        if close.index[pos] > deadline:
            break
        if close.iloc[pos] >= peg_target:
            return float(close.iloc[pos])
    exit_px, _ = _forward_exit(close, t0_pos, horizon_days)
    return exit_px


def build_events(
    close: pd.Series,
    symbol: str,
    *,
    is_dead_coin: bool,
    threshold: float = DEPEG_THRESHOLD,
    rearm_level: float = REARM_LEVEL,
    horizon_days: int = HORIZON_DAYS,
    peg_target: float = PEG_TARGET,
) -> list[DepegEvent]:
    """PURE: full :class:`DepegEvent` list for one symbol's close series.

    ``is_dead_coin`` is the pre-registered, externally-known classification
    (UST/USTC == dead) so the survivorship split does not depend on the data
    itself. ``terminal`` (series-ran-out) is derived from the data and is a
    *separate* fact — a coin can be classified dead and also be terminal in the
    window; both are reported.
    """

    if close is None or close.empty:
        return []
    close = close[~close.index.duplicated(keep="last")].sort_index()
    out: list[DepegEvent] = []
    positions = {ts: i for i, ts in enumerate(close.index)}
    for ts in find_depeg_events(close, threshold=threshold, rearm_level=rearm_level):
        pos = positions[ts]
        entry = float(close.iloc[pos])
        if entry <= 0:
            continue
        exit_7d, _ = _forward_exit(close, pos, 7)
        exit_30d, terminal = _forward_exit(close, pos, horizon_days)
        exit_peg = _forward_to_peg(close, pos, horizon_days, peg_target)
        recovered = exit_peg >= peg_target
        out.append(
            DepegEvent(
                symbol=symbol,
                t0=ts.date(),
                entry=entry,
                exit_7d=exit_7d,
                exit_30d=exit_30d,
                exit_to_peg=exit_peg,
                ret_7d=exit_7d / entry - 1.0,
                ret_30d=exit_30d / entry - 1.0,
                ret_to_peg=exit_peg / entry - 1.0,
                recovered=recovered,
                terminal=terminal,
                is_dead_coin=is_dead_coin,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Distribution / gate stats (PURE)
# --------------------------------------------------------------------------- #
def after_cost(gross: np.ndarray, cost: float = ROUND_TRIP_COST) -> np.ndarray:
    """PURE: subtract one round-trip cost from each gross return."""

    return np.asarray(gross, dtype=float) - cost


def t_stat(x: np.ndarray) -> float:
    """PURE: one-sample t-stat vs 0 (0.0 if <2 points or zero variance)."""

    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 2:
        return 0.0
    sd = x.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(x.mean() / (sd / np.sqrt(n)))


def distribution_summary(rets: np.ndarray) -> dict[str, float]:
    """PURE: the tail/skew picture — the whole point of a short-vol strategy.

    Reports median vs mean (median >> mean is the short-vol tell), the left
    tail (min, p5), win rate, and skew. ``worst_contribution`` is the single
    worst event's share of the summed return (how much one corpse dominates).
    """

    r = np.asarray(rets, dtype=float)
    n = r.size
    if n == 0:
        return {"n": 0}
    total = float(r.sum())
    worst = float(r.min())
    return {
        "n": float(n),
        "mean": float(r.mean()),
        "median": float(np.median(r)),
        "std": float(r.std(ddof=1)) if n >= 2 else 0.0,
        "min": worst,
        "p5": float(np.percentile(r, 5)),
        "max": float(r.max()),
        "win_rate": float((r > 0).mean()),
        "skew": _skew(r),
        "t_stat": t_stat(r),
        "worst_contribution": (worst / total) if total != 0 else float("nan"),
    }


def _skew(x: np.ndarray) -> float:
    """PURE: sample skewness (0.0 if <3 points or zero variance)."""

    x = np.asarray(x, dtype=float)
    n = x.size
    if n < 3:
        return 0.0
    sd = x.std(ddof=0)
    if sd == 0:
        return 0.0
    return float(((x - x.mean()) ** 3).mean() / sd**3)


def survivorship_split(
    events: list[DepegEvent], window: str = "ret_30d", cost: float = ROUND_TRIP_COST
) -> dict[str, dict[str, float]]:
    """PURE: the headline — after-cost stats WITH vs WITHOUT dead coins.

    ``with_dead`` is the full, honest sample; ``survivor_only`` drops every event
    on a coin classified dead (UST/USTC). If ``survivor_only`` is positive but
    ``with_dead`` is <= 0, the strategy is a survivorship artifact — the
    pre-registered kill. ``window`` selects the forward field (``ret_30d`` is
    PRIMARY).
    """

    def stats(evs: list[DepegEvent]) -> dict[str, float]:
        g = np.array([getattr(e, window) for e in evs], dtype=float)
        return distribution_summary(after_cost(g, cost))

    survivors = [e for e in events if not e.is_dead_coin]
    return {
        "with_dead": stats(events),
        "survivor_only": stats(survivors),
        "n_dead_events": float(sum(1 for e in events if e.is_dead_coin)),
        "n_terminal_events": float(sum(1 for e in events if e.terminal)),
    }


def is_oos_split(
    events: list[DepegEvent], window: str = "ret_30d", oos_start: date = OOS_START,
    cost: float = ROUND_TRIP_COST,
) -> dict[str, dict[str, float]]:
    """PURE: after-cost stats for IS (t0 < oos_start) vs OOS halves (full sample)."""

    def stats(evs: list[DepegEvent]) -> dict[str, float]:
        g = np.array([getattr(e, window) for e in evs], dtype=float)
        return distribution_summary(after_cost(g, cost))

    return {
        "is": stats([e for e in events if e.t0 < oos_start]),
        "oos": stats([e for e in events if e.t0 >= oos_start]),
    }


def drop_worst(events: list[DepegEvent], window: str = "ret_30d") -> list[DepegEvent]:
    """PURE: the full event list minus the single worst event by ``window``.

    Used for the pre-registered tail-domination check: if removing one event
    flips the after-cost sign, the tail dominates and the edge is not real.
    """

    if not events:
        return []
    worst = min(events, key=lambda e: getattr(e, window))
    return [e for e in events if e is not worst]


def placebo_stats(
    close_by_symbol: dict[str, pd.Series],
    n_per_symbol: int,
    *,
    window_days: int = HORIZON_DAYS,
    cost: float = ROUND_TRIP_COST,
    seed: int = 20260614,
) -> dict[str, float]:
    """PURE: random non-event entry dates on the same symbols -> forward returns.

    Draws ``n_per_symbol`` random t0 positions from each symbol's NON-event days
    (close >= threshold) and measures the same fixed-horizon forward return. The
    depeg signal must beat this baseline drift toward $1. Deterministic via
    ``seed``. Operates on in-memory series only (no network).
    """

    rng = np.random.default_rng(seed)
    rets: list[float] = []
    for _sym, close in close_by_symbol.items():
        if close is None or close.empty:
            continue
        close = close[~close.index.duplicated(keep="last")].sort_index()
        non_event = np.where(close.to_numpy() >= DEPEG_THRESHOLD)[0]
        non_event = non_event[non_event < len(close) - 1]
        if non_event.size == 0:
            continue
        k = min(n_per_symbol, non_event.size)
        for pos in rng.choice(non_event, size=k, replace=False):
            entry = float(close.iloc[pos])
            if entry <= 0:
                continue
            exit_px, _ = _forward_exit(close, int(pos), window_days)
            rets.append(exit_px / entry - 1.0)
    return distribution_summary(after_cost(np.array(rets, dtype=float), cost))


def evaluate_gate(events: list[DepegEvent], window: str = "ret_30d") -> dict[str, object]:
    """PURE: apply the pre-registered gate and return PASS/FAIL flags + numbers.

    The verdict logic encodes the pre-reg: claim an edge ONLY if N>=30 AND the
    WITH-dead after-cost mean is positive with |t|>=2 AND survivor-inclusion did
    not flip the sign AND dropping the worst event does not flip the sign.
    """

    split = survivorship_split(events, window=window)
    with_dead = split["with_dead"]
    survivor = split["survivor_only"]
    n = int(with_dead.get("n", 0))

    dropped = drop_worst(events, window=window)
    g_dropped = np.array([getattr(e, window) for e in dropped], dtype=float)
    drop_mean = float(after_cost(g_dropped).mean()) if g_dropped.size else 0.0

    with_mean = with_dead.get("mean", 0.0)
    with_t = with_dead.get("t_stat", 0.0)
    surv_mean = survivor.get("mean", 0.0)

    n_ok = n >= 30
    signal_ok = with_mean > 0 and abs(with_t) >= 2.0
    survivorship_ok = not (surv_mean > 0 and with_mean <= 0)  # corpses didn't flip it
    tail_ok = not ((with_mean > 0) ^ (drop_mean > 0))  # sign stable to worst-drop

    survives = bool(n_ok and signal_ok and survivorship_ok and tail_ok)
    return {
        "n": n,
        "with_dead_mean": with_mean,
        "with_dead_t": with_t,
        "survivor_only_mean": surv_mean,
        "drop_worst_mean": drop_mean,
        "n_ok": n_ok,
        "signal_ok": signal_ok,
        "survivorship_ok": survivorship_ok,
        "tail_ok": tail_ok,
        "survives": survives,
    }
