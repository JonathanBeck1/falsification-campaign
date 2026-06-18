"""Historical replay reporting with train/test and cost diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from trader.research.data_coverage import DataCoverage, build_data_coverage, format_data_coverage
from trader.scoring.leaderboard import LeaderboardRow, build_leaderboard
from trader.storage.store import Store


@dataclass(frozen=True)
class ReplayReportConfig:
    ticker: str
    since: date
    until: date
    train_until: date | None
    cost_bps: float
    baseline: str
    min_days: int
    starting_cash: float


@dataclass(frozen=True)
class ReplayCostStats:
    trades: int
    filled_notional: float
    estimated_cost_usd: float
    estimated_cost_return: float


@dataclass(frozen=True)
class ReplayReportRow:
    brain: str
    days: int
    gross_total_return: float
    net_total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    hit_rate: float
    trades: int
    filled_notional: float
    estimated_cost_usd: float
    vs_baseline_net_pp: float
    confidence_tier: str


@dataclass(frozen=True)
class ReplayWindowReport:
    name: str
    since: date
    until: date
    rows: list[ReplayReportRow]


@dataclass(frozen=True)
class ReplayReport:
    config: ReplayReportConfig
    historical_bar_rows: int
    windows: list[ReplayWindowReport]
    data_coverage: DataCoverage


def build_replay_report(store: Store, config: ReplayReportConfig) -> ReplayReport:
    if config.since > config.until:
        raise ValueError("since must be on or before until")
    if config.cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    if config.min_days < 1:
        raise ValueError("min_days must be at least 1")
    if config.train_until is not None and not (config.since <= config.train_until < config.until):
        raise ValueError("train_until must be inside [since, until)")

    windows = [_build_window(store, config=config, name="full", since=config.since, until=config.until)]
    if config.train_until is not None:
        windows.append(
            _build_window(
                store,
                config=config,
                name="train",
                since=config.since,
                until=config.train_until,
            )
        )
        windows.append(
            _build_window(
                store,
                config=config,
                name="test",
                since=config.train_until + timedelta(days=1),
                until=config.until,
            )
        )

    return ReplayReport(
        config=config,
        historical_bar_rows=len(
            store.get_historical_bars(config.ticker, since=config.since.isoformat(), until=config.until.isoformat())
        ),
        windows=windows,
        data_coverage=build_data_coverage(store),
    )


def format_replay_report(report: ReplayReport) -> str:
    cfg = report.config
    lines = [
        "# Historical Replay Report",
        "",
        "Research-only replay diagnostics. This is not proof of edge, a live signal, or investment advice.",
        "",
        "## Run Metadata",
        "",
        f"- ticker: {cfg.ticker}",
        f"- since: {cfg.since.isoformat()}",
        f"- until: {cfg.until.isoformat()}",
        f"- train_until: {cfg.train_until.isoformat() if cfg.train_until else 'not set'}",
        f"- baseline: {cfg.baseline}",
        f"- min_days: {cfg.min_days}",
        f"- cost_bps: {cfg.cost_bps:.2f}",
        f"- starting_cash: {cfg.starting_cash:.2f}",
        f"- historical_bar_rows: {report.historical_bar_rows}",
        "",
        "## Replay Windows",
        "",
    ]
    for window in report.windows:
        lines.extend(_format_window(window))
        lines.append("")

    lines.extend(
        [
            "## Interpretation",
            "",
            "- Gross returns come from `brain_equity_curve`.",
            "- Estimated cost uses filled notional joined through decision snapshot trade dates.",
            "- Windowed trade counts do not use order submit timestamps, because historical replay submits orders at runtime.",
            "- Treat this as a triage report. Any candidate still needs out-of-sample, regime, slippage, and paper-trading validation.",
            "",
            "## Data Coverage",
            "",
        ]
    )
    coverage = format_data_coverage(report.data_coverage).splitlines()
    # Drop the nested top-level title to keep this report hierarchy clean.
    lines.extend(coverage[1:])
    return "\n".join(lines).rstrip() + "\n"


def _build_window(
    store: Store,
    *,
    config: ReplayReportConfig,
    name: str,
    since: date,
    until: date,
) -> ReplayWindowReport:
    leaderboard_rows = [
        row
        for row in build_leaderboard(store, since=since, until=until, baseline_brain=config.baseline)
        if row.days >= config.min_days
    ]
    costs = _cost_stats_by_brain(
        store,
        since=since,
        until=until,
        cost_bps=config.cost_bps,
        starting_cash=config.starting_cash,
    )
    baseline_net = _net_total_for_brain(leaderboard_rows, costs, config.baseline)
    rows = [
        _report_row(row, costs.get(row.brain), baseline_net=baseline_net)
        for row in leaderboard_rows
    ]
    return ReplayWindowReport(name=name, since=since, until=until, rows=rows)


def _report_row(
    row: LeaderboardRow,
    cost: ReplayCostStats | None,
    *,
    baseline_net: float | None,
) -> ReplayReportRow:
    cost = cost or ReplayCostStats(trades=0, filled_notional=0.0, estimated_cost_usd=0.0, estimated_cost_return=0.0)
    net_return = row.total_return - cost.estimated_cost_return
    return ReplayReportRow(
        brain=row.brain,
        days=row.days,
        gross_total_return=row.total_return,
        net_total_return=net_return,
        annualized_return=row.annualized_return,
        sharpe=row.sharpe,
        max_drawdown=row.max_drawdown,
        hit_rate=row.hit_rate,
        trades=cost.trades,
        filled_notional=cost.filled_notional,
        estimated_cost_usd=cost.estimated_cost_usd,
        vs_baseline_net_pp=((net_return - baseline_net) * 100.0 if baseline_net is not None else 0.0),
        confidence_tier=row.confidence_tier,
    )


def _net_total_for_brain(
    rows: list[LeaderboardRow],
    costs: dict[str, ReplayCostStats],
    brain: str,
) -> float | None:
    for row in rows:
        if row.brain == brain:
            cost = costs.get(brain)
            return row.total_return - (cost.estimated_cost_return if cost else 0.0)
    return None


def _cost_stats_by_brain(
    store: Store,
    *,
    since: date,
    until: date,
    cost_bps: float,
    starting_cash: float,
) -> dict[str, ReplayCostStats]:
    with store._conn() as conn:
        rows = conn.execute(
            """
            SELECT
                o.brain AS brain,
                COUNT(DISTINCT o.client_order_id) AS trades,
                COALESCE(SUM(f.filled_qty * f.filled_avg_price), 0.0) AS filled_notional
            FROM orders o
            JOIN decisions d ON d.decision_id = o.decision_id
            JOIN snapshots s ON s.snapshot_id = d.snapshot_id
            LEFT JOIN fills f ON f.client_order_id = o.client_order_id
            WHERE s.trade_date >= ? AND s.trade_date <= ?
            GROUP BY o.brain
            ORDER BY o.brain
            """,
            (since.isoformat(), until.isoformat()),
        ).fetchall()
    out: dict[str, ReplayCostStats] = {}
    for row in rows:
        notional = float(row["filled_notional"] or 0.0)
        cost_usd = notional * (cost_bps / 10_000.0)
        out[str(row["brain"])] = ReplayCostStats(
            trades=int(row["trades"] or 0),
            filled_notional=notional,
            estimated_cost_usd=cost_usd,
            estimated_cost_return=(cost_usd / starting_cash if starting_cash > 0 else 0.0),
        )
    return out


def _format_window(window: ReplayWindowReport) -> list[str]:
    lines = [
        f"### {window.name.title()} Window",
        "",
        f"- since: {window.since.isoformat()}",
        f"- until: {window.until.isoformat()}",
        "",
    ]
    if not window.rows:
        lines.append("No brains met the minimum day count for this window.")
        return lines
    lines.extend(
        [
            "| brain | tier | days | gross_tot_ret | net_tot_ret | ann_ret | sharpe | max_dd | hit_rate | trades | filled_notional | est_cost | vs_baseline_net |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in window.rows:
        lines.append(
            f"| {_cell(row.brain)} | {_cell(row.confidence_tier)} | {row.days} | "
            f"{_pct(row.gross_total_return)} | {_pct(row.net_total_return)} | "
            f"{_pct(row.annualized_return)} | {row.sharpe:.2f} | {_pct(row.max_drawdown)} | "
            f"{row.hit_rate:.2f} | {row.trades} | {row.filled_notional:.2f} | "
            f"{row.estimated_cost_usd:.2f} | {row.vs_baseline_net_pp:+.2f}pp |"
        )
    return lines


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")
