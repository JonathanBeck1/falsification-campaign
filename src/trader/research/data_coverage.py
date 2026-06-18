"""Local data coverage reporting.

This module is deliberately read-only. It answers the operator question:
"What data do we actually have in this SQLite file right now?"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trader.storage.store import Store


@dataclass(frozen=True)
class HistoricalBarsCoverage:
    ticker: str
    rows: int
    first_trade_date: str
    last_trade_date: str
    vix_rows: int
    yield_curve_rows: int


@dataclass(frozen=True)
class NewsEventsCoverage:
    source: str
    event_type: str
    rows: int
    first_observed_at: str
    last_observed_at: str
    classified_rows: int
    enriched_rows: int


@dataclass(frozen=True)
class SourceFetchCoverage:
    source: str
    latest_status: str
    attempts: int
    ok_count: int
    error_count: int
    latest_attempted_at: str
    latest_item_count: int
    latest_persisted_count: int


@dataclass(frozen=True)
class DataCoverage:
    historical_bars: list[HistoricalBarsCoverage]
    news_events: list[NewsEventsCoverage]
    source_fetches: list[SourceFetchCoverage]
    total_news_events: int
    enriched_news_events: int
    research_runs: int
    paper_trade_intents: int


def build_data_coverage(store: Store) -> DataCoverage:
    """Build a read-only coverage snapshot from SQLite."""
    with store._conn() as conn:
        bar_rows = conn.execute(
            """
            SELECT
                ticker,
                COUNT(*) AS rows,
                MIN(trade_date) AS first_trade_date,
                MAX(trade_date) AS last_trade_date,
                SUM(CASE WHEN vix_close IS NOT NULL THEN 1 ELSE 0 END) AS vix_rows,
                SUM(CASE WHEN yield_curve_10y_2y IS NOT NULL THEN 1 ELSE 0 END) AS yield_curve_rows
            FROM historical_bars
            GROUP BY ticker
            ORDER BY ticker
            """
        ).fetchall()
        news_rows = conn.execute(
            """
            SELECT
                source,
                event_type,
                COUNT(*) AS rows,
                MIN(observed_at) AS first_observed_at,
                MAX(observed_at) AS last_observed_at,
                SUM(CASE WHEN classified_at IS NOT NULL THEN 1 ELSE 0 END) AS classified_rows,
                SUM(CASE WHEN model_outputs_json IS NOT NULL AND model_outputs_json != '[]' THEN 1 ELSE 0 END)
                    AS enriched_rows
            FROM news_events
            GROUP BY source, event_type
            ORDER BY source, event_type
            """
        ).fetchall()
        total_news = int(conn.execute("SELECT COUNT(*) AS n FROM news_events").fetchone()["n"])
        enriched_news = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM news_events
                WHERE model_outputs_json IS NOT NULL AND model_outputs_json != '[]'
                """
            ).fetchone()["n"]
        )
        research_runs = int(conn.execute("SELECT COUNT(*) AS n FROM research_runs").fetchone()["n"])
        paper_intents = int(conn.execute("SELECT COUNT(*) AS n FROM paper_trade_intents").fetchone()["n"])

    source_fetches = [
        SourceFetchCoverage(
            source=str(row["source"]),
            latest_status=str(row["latest_status"]),
            attempts=int(row["attempt_count"]),
            ok_count=int(row["ok_count"]),
            error_count=int(row["error_count"]),
            latest_attempted_at=str(row["latest_attempted_at"] or ""),
            latest_item_count=int(row["latest_item_count"] or 0),
            latest_persisted_count=int(row["latest_persisted_count"] or 0),
        )
        for row in store.source_fetch_summary(limit=1000)
    ]

    return DataCoverage(
        historical_bars=[
            HistoricalBarsCoverage(
                ticker=str(row["ticker"]),
                rows=int(row["rows"]),
                first_trade_date=str(row["first_trade_date"] or ""),
                last_trade_date=str(row["last_trade_date"] or ""),
                vix_rows=int(row["vix_rows"] or 0),
                yield_curve_rows=int(row["yield_curve_rows"] or 0),
            )
            for row in bar_rows
        ],
        news_events=[
            NewsEventsCoverage(
                source=str(row["source"]),
                event_type=str(row["event_type"]),
                rows=int(row["rows"]),
                first_observed_at=str(row["first_observed_at"] or ""),
                last_observed_at=str(row["last_observed_at"] or ""),
                classified_rows=int(row["classified_rows"] or 0),
                enriched_rows=int(row["enriched_rows"] or 0),
            )
            for row in news_rows
        ],
        source_fetches=source_fetches,
        total_news_events=total_news,
        enriched_news_events=enriched_news,
        research_runs=research_runs,
        paper_trade_intents=paper_intents,
    )


def format_data_coverage(coverage: DataCoverage) -> str:
    lines = [
        "# Data Coverage Report",
        "",
        "Research-only inventory of the local SQLite database. Counts here are not an edge claim.",
        "",
        "## Summary",
        "",
        f"- historical_bar_tickers: {len(coverage.historical_bars)}",
        f"- total_news_events: {coverage.total_news_events}",
        f"- enriched_news_events: {coverage.enriched_news_events}",
        f"- research_runs: {coverage.research_runs}",
        f"- paper_trade_intents: {coverage.paper_trade_intents}",
        "",
        "## Historical Bars",
        "",
    ]
    if not coverage.historical_bars:
        lines.append("No historical bars found. Run `trader-daily backfill-prices` first.")
    else:
        lines.extend(
            [
                "| ticker | rows | first_trade_date | last_trade_date | vix_rows | yield_curve_rows |",
                "|---|---:|---|---|---:|---:|",
            ]
        )
        for row in coverage.historical_bars:
            lines.append(
                f"| {_cell(row.ticker)} | {row.rows} | {_cell(row.first_trade_date)} | "
                f"{_cell(row.last_trade_date)} | {row.vix_rows} | {row.yield_curve_rows} |"
            )

    lines.extend(["", "## News Events", ""])
    if not coverage.news_events:
        lines.append("No news_events rows found. Run `trader-daily fetch-events` or seed demo events.")
    else:
        lines.extend(
            [
                "| source | event_type | rows | classified | enriched | first_observed_at | last_observed_at |",
                "|---|---|---:|---:|---:|---|---|",
            ]
        )
        for row in coverage.news_events:
            lines.append(
                f"| {_cell(row.source)} | {_cell(row.event_type)} | {row.rows} | "
                f"{row.classified_rows} | {row.enriched_rows} | {_cell(row.first_observed_at)} | "
                f"{_cell(row.last_observed_at)} |"
            )

    lines.extend(["", "## Source Fetches", ""])
    if not coverage.source_fetches:
        lines.append("No source fetch ledger rows found.")
    else:
        lines.extend(
            [
                "| source | latest_status | attempts | ok | errors | latest_items | latest_persisted | latest_attempted_at |",
                "|---|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in coverage.source_fetches:
            lines.append(
                f"| {_cell(row.source)} | {_cell(row.latest_status)} | {row.attempts} | "
                f"{row.ok_count} | {row.error_count} | {row.latest_item_count} | "
                f"{row.latest_persisted_count} | {_cell(row.latest_attempted_at)} |"
            )

    lines.extend(
        [
            "",
            "## Data Gaps",
            "",
            "- No historical news backfill is present. Current news adapters collect recent/live-ish events only.",
            "- Historical replay currently proves price/macro plumbing for six deterministic brains, not event-driven alpha.",
            "- To collect more data without paid APIs: backfill broader daily bars, run scheduled event fetches, enrich stored events, then run outcome studies.",
            "",
        ]
    )
    return "\n".join(lines)


def _cell(value: Any) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")
