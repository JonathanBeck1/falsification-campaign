from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trader.enrichment.review import enrichment_bucket
from trader.normalization.models import event_from_row
from trader.research.event_candidates import score_events


@dataclass(frozen=True)
class StoreMetrics:
    total_events: int
    total_decisions: int
    total_orders: int
    latest_event_at: str | None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(conn: sqlite3.Connection, sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    return row[0] if row else None


def store_metrics(db_path: Path) -> StoreMetrics:
    with _connect(db_path) as conn:
        return StoreMetrics(
            total_events=int(_scalar(conn, "SELECT COUNT(*) FROM news_events") or 0),
            total_decisions=int(_scalar(conn, "SELECT COUNT(*) FROM decisions") or 0),
            total_orders=int(_scalar(conn, "SELECT COUNT(*) FROM orders") or 0),
            latest_event_at=_scalar(conn, "SELECT MAX(published_at) FROM news_events"),
        )


def source_counts(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT source, COUNT(*) AS count
            FROM news_events
            GROUP BY source
            ORDER BY count DESC, source
            """
        ).fetchall()
        return [dict(row) for row in rows]


def event_type_counts(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS count
            FROM news_events
            GROUP BY event_type
            ORDER BY count DESC, event_type
            """
        ).fetchall()
        return [dict(row) for row in rows]


def recent_events(db_path: Path, *, limit: int = 25) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT published_at, source, event_type, urgency, title
            FROM news_events
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def _parsed_events(db_path: Path, *, limit: int = 10_000) -> list:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM news_events ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall()
        return [event_from_row(dict(row)) for row in rows]


def enrichment_status_counts(db_path: Path) -> list[dict[str, Any]]:
    counts = {"enriched": 0, "rejected": 0, "missing": 0}
    for event in _parsed_events(db_path):
        counts[enrichment_bucket(event)] += 1
    return [{"bucket": bucket, "count": count} for bucket, count in counts.items() if count]


def event_candidate_rows(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    candidates = score_events(_parsed_events(db_path))
    rows: list[dict[str, Any]] = []
    for candidate in candidates[:limit]:
        rows.append(
            {
                "published_at": candidate.published_at.isoformat(),
                "ticker": candidate.ticker,
                "direction": candidate.direction,
                "score": candidate.score,
                "confidence": candidate.confidence,
                "actionable": candidate.is_actionable,
                "event_type": candidate.event_type,
                "source": candidate.source,
                "title": candidate.title,
            }
        )
    return rows


def latest_system_events(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT created_at, level, source, message
            FROM events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def _source_health(status: object, persisted_count: object) -> str:
    if status == "error":
        return "failing"
    if status == "empty" or int(persisted_count or 0) == 0:
        return "degraded"
    return "healthy"


def source_quality_rows(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM source_fetches
                ORDER BY attempted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: source_fetches" in str(exc):
                return []
            raise

    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = dict(row)
        source = str(data["source"])
        current = summary.setdefault(
            source,
            {
                "source": source,
                "latest_fetch_id": data["fetch_id"],
                "latest_attempted_at": data["attempted_at"],
                "latest_finished_at": data["finished_at"],
                "latest_status": data["status"],
                "latest_item_count": data["item_count"],
                "latest_persisted_count": data["persisted_count"],
                "latest_latency_ms": data["latency_ms"],
                "latest_error": data["error"],
                "attempt_count": 0,
                "ok_count": 0,
                "empty_count": 0,
                "error_count": 0,
                "health": _source_health(data["status"], data["persisted_count"]),
            },
        )
        current["attempt_count"] += 1
        status = str(data["status"])
        if status == "ok":
            current["ok_count"] += 1
        elif status == "empty":
            current["empty_count"] += 1
        elif status == "error":
            current["error_count"] += 1

    rows_out = list(summary.values())
    rows_out.sort(key=lambda item: (item["health"] != "failing", str(item["source"])))
    return rows_out


def _report_category(path: Path) -> str:
    name = path.stem.lower()
    if "outcome" in name and "review" in name:
        return "outcome_review"
    if "outcome" in name or "backtest" in name:
        return "backtest"
    if "daily" in name or "brief" in name:
        return "daily"
    if "event" in name or "candidate" in name:
        return "event_research"
    return "research"


def report_file_rows(reports_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in list_report_files(reports_dir):
        stat = path.stat()
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "category": _report_category(path),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                "size_bytes": stat.st_size,
            }
        )
    return rows


def attention_items(
    *,
    metrics: StoreMetrics | None,
    enrichment: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    system_events: list[dict[str, Any]],
    source_quality: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if metrics is None:
        items.append(
            {
                "level": "warning",
                "label": "Database missing",
                "detail": "Run the event fetch workflow before reviewing the terminal.",
            }
        )
    elif metrics.total_events == 0:
        items.append(
            {
                "level": "warning",
                "label": "No events stored",
                "detail": "The local store is present but has no normalized news events.",
            }
        )

    missing_count = sum(row["count"] for row in enrichment if row.get("bucket") == "missing")
    rejected_count = sum(row["count"] for row in enrichment if row.get("bucket") == "rejected")
    if missing_count:
        items.append(
            {
                "level": "warning",
                "label": "Enrichment backlog",
                "detail": f"{missing_count:,} events are missing enrichment output.",
            }
        )
    if rejected_count:
        items.append(
            {
                "level": "info",
                "label": "Rejected enrichments",
                "detail": f"{rejected_count:,} events were rejected or abstained.",
            }
        )
    if candidates:
        items.append(
            {
                "level": "success",
                "label": "Candidates waiting",
                "detail": f"{len(candidates):,} scored candidates are ready for Event Lab review.",
            }
        )
    if not reports:
        items.append(
            {
                "level": "warning",
                "label": "Reports missing",
                "detail": "Generate a markdown report before reviewing Backtest Lab.",
            }
        )
    error_count = sum(
        1
        for row in system_events
        if str(row.get("level", "")).lower() in {"error", "critical", "exception", "kill"}
    )
    if error_count:
        items.append(
            {
                "level": "error",
                "label": "System errors",
                "detail": f"{error_count:,} recent system events need attention.",
            }
        )
    for row in (source_quality or []):
        if row.get("latest_status") != "error":
            continue
        source = str(row.get("source") or "unknown")
        error = str(row.get("latest_error") or "no error detail")
        items.append(
            {
                "level": "error",
                "label": "Source fetch failed",
                "detail": f"{source} latest fetch failed: {error}",
            }
        )
    if not items:
        items.append(
            {
                "level": "success",
                "label": "Pipeline quiet",
                "detail": "No immediate operator action detected.",
            }
        )
    return items


def _json_list(raw: Any) -> list[Any]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _tickers_from_row(row: dict[str, Any]) -> list[str]:
    tickers: set[str] = set()
    for entity in _json_list(row.get("entities_json")):
        if not isinstance(entity, dict):
            continue
        ticker = entity.get("ticker") or entity.get("name")
        if ticker:
            tickers.add(str(ticker).upper())
    for ticker in _json_list(row.get("index_exposure_json")):
        if ticker:
            tickers.add(str(ticker).upper())
    return sorted(tickers)


def news_tape_rows(db_path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, published_at, observed_at, source, event_type, sentiment, sentiment_score,
                   urgency, title, source_url, entities_json, index_exposure_json
            FROM news_events
            ORDER BY observed_at DESC, published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        tickers = _tickers_from_row(data)
        out.append(
            {
                "event_id": data["event_id"],
                "observed_at": data["observed_at"],
                "published_at": data["published_at"],
                "tickers": ", ".join(tickers) if tickers else "UNMAPPED",
                "source": data["source"],
                "event_type": data["event_type"],
                "urgency": data["urgency"],
                "sentiment": data["sentiment"],
                "sentiment_score": data["sentiment_score"],
                "title": data["title"],
                "source_url": data["source_url"],
            }
        )
    return out


def ticker_activity_rows(db_path: Path, *, limit: int = 25) -> list[dict[str, Any]]:
    activity: dict[str, dict[str, Any]] = {}
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT published_at, source, event_type, title, entities_json, index_exposure_json
            FROM news_events
            ORDER BY published_at DESC
            LIMIT 1000
            """
        ).fetchall()

    for row in rows:
        data = dict(row)
        tickers = _tickers_from_row(data) or ["UNMAPPED"]
        for ticker in tickers:
            current = activity.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "event_count": 0,
                    "latest_event_at": data["published_at"],
                    "latest_source": data["source"],
                    "latest_type": data["event_type"],
                    "latest_title": data["title"],
                },
            )
            current["event_count"] += 1
            if data["published_at"] >= current["latest_event_at"]:
                current["latest_event_at"] = data["published_at"]
                current["latest_source"] = data["source"]
                current["latest_type"] = data["event_type"]
                current["latest_title"] = data["title"]

    rows_out = list(activity.values())
    rows_out.sort(key=lambda item: (-int(item["event_count"]), item["ticker"]))
    return rows_out[:limit]


def recent_decision_rows(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT created_at, brain, action, target_pct, confidence, llm_cost_usd, reasoning
            FROM decisions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def recent_order_rows(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT submitted_at, brain, ticker, side, qty, order_type, limit_price, status, alpaca_order_id
            FROM orders
            ORDER BY submitted_at DESC
            LIMIT ?
            """,
            (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def paper_intent_rows(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT intent_id, event_id, created_at, ticker, direction, candidate_score,
                       confidence, proposed_action, proposed_target_pct, risk_status,
                       risk_reason, final_action, final_qty, simulated_order_id, status,
                       source, event_type, title
                FROM paper_trade_intents
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: paper_trade_intents" in str(exc):
                return []
            raise
        return [dict(row) for row in rows]


def research_run_rows(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT run_id, started_at, finished_at, status, benchmark, entry_time,
                       events_before, events_after, enriched_count, rejected_count,
                       candidate_count, outcome_report_path, review_report_path, manifest_path, error
                FROM research_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: research_runs" in str(exc):
                return []
            raise
        return [dict(row) for row in rows]


def list_report_files(reports_dir: Path) -> list[Path]:
    if not reports_dir.exists():
        return []
    reports = [path for path in reports_dir.glob("*.md") if path.is_file()]
    reports.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return reports


def latest_decision_per_brain(db_path: Path) -> list[dict[str, Any]]:
    """One row per brain: the most recent decision the brain emitted."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT d.brain, d.action, d.target_pct, d.confidence, d.reasoning,
                   d.llm_cost_usd, d.created_at
            FROM decisions d
            JOIN (
                SELECT brain, MAX(created_at) AS latest
                FROM decisions
                GROUP BY brain
            ) latest_d
              ON latest_d.brain = d.brain AND latest_d.latest = d.created_at
            ORDER BY d.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def brain_portfolio_rows(db_path: Path) -> list[dict[str, Any]]:
    """Per-brain current portfolio state plus latest equity and 1d change."""
    with _connect(db_path) as conn:
        try:
            portfolios = conn.execute(
                """
                SELECT brain, cash, position_qty, avg_cost, realized_pnl, updated_at
                FROM brain_portfolios
                ORDER BY brain
                """
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: brain_portfolios" in str(exc):
                return []
            raise
        equity_rows = conn.execute(
            """
            SELECT brain, trade_date, equity
            FROM brain_equity_curve
            ORDER BY brain, trade_date DESC
            """
        ).fetchall()

    latest: dict[str, dict[str, Any]] = {}
    prior: dict[str, dict[str, Any]] = {}
    for row in equity_rows:
        brain = row["brain"]
        if brain not in latest:
            latest[brain] = dict(row)
        elif brain not in prior:
            prior[brain] = dict(row)

    out: list[dict[str, Any]] = []
    for row in portfolios:
        data = dict(row)
        brain = data["brain"]
        latest_eq = latest.get(brain)
        prior_eq = prior.get(brain)
        equity = float(latest_eq["equity"]) if latest_eq else float(data["cash"])
        prior_equity = float(prior_eq["equity"]) if prior_eq else equity
        change_pct = ((equity - prior_equity) / prior_equity * 100.0) if prior_equity else 0.0
        out.append(
            {
                "brain": brain,
                "cash": float(data["cash"]),
                "position_qty": float(data["position_qty"]),
                "avg_cost": float(data["avg_cost"]),
                "realized_pnl": float(data["realized_pnl"]),
                "equity": equity,
                "equity_prior": prior_equity,
                "equity_change_pct": change_pct,
                "equity_date": latest_eq["trade_date"] if latest_eq else None,
                "updated_at": data["updated_at"],
            }
        )
    return out


def recent_fill_rows(db_path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent executed fills joined to their parent orders."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT f.fill_id, f.filled_at, f.filled_qty, f.filled_avg_price,
                   o.brain, o.ticker, o.side, o.order_type, o.status
            FROM fills f
            JOIN orders o ON o.client_order_id = f.client_order_id
            ORDER BY f.filled_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def active_halts(db_path: Path, *, hours: int = 24, limit: int = 20) -> list[dict[str, Any]]:
    """Recent kill/error system events — what's blocking trading right now."""
    cutoff = datetime.now(UTC).timestamp() - hours * 3600
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT created_at, level, source, message
            FROM events
            WHERE created_at >= ?
              AND lower(level) IN ('kill', 'error', 'critical', 'exception')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff_iso, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def todays_paper_intents(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Paper intents created in the last 24h, freshest first."""
    cutoff = datetime.now(UTC).timestamp() - 24 * 3600
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()
    with _connect(db_path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT intent_id, event_id, created_at, ticker, direction, candidate_score,
                       confidence, proposed_action, proposed_target_pct, risk_status,
                       risk_reason, final_action, final_qty, simulated_order_id, status,
                       source, event_type, title
                FROM paper_trade_intents
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (cutoff_iso, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: paper_trade_intents" in str(exc):
                return []
            raise
        return [dict(row) for row in rows]


_PERIOD_TO_YF: dict[str, tuple[str, str]] = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "30m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "1Y": ("1y", "1d"),
}


def historical_quotes(tickers: list[str], period: str = "1M") -> list[dict[str, Any]]:
    """Per-ticker price series + period summary for the LIVE chart cards.

    Returns one row per ticker with: last, first (period start), change,
    change_pct, points (list of {t, price} for the sparkline). On any
    per-ticker error the row carries status="error".
    """
    try:
        import yfinance as yf
    except ImportError:
        return [{"ticker": t, "status": "yfinance_missing"} for t in tickers]

    yf_period, yf_interval = _PERIOD_TO_YF.get(period, _PERIOD_TO_YF["1M"])

    out: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(period=yf_period, interval=yf_interval)
            if df.empty:
                out.append({"ticker": ticker, "status": "no_data", "period": period})
                continue
            closes = df["Close"].dropna()
            if closes.empty:
                out.append({"ticker": ticker, "status": "no_data", "period": period})
                continue
            first = float(closes.iloc[0])
            last = float(closes.iloc[-1])
            change = last - first
            change_pct = (change / first * 100.0) if first else 0.0
            points = [
                {"t": idx.isoformat(), "price": float(value)}
                for idx, value in closes.items()
            ]
            out.append(
                {
                    "ticker": ticker,
                    "status": "ok",
                    "period": period,
                    "first": first,
                    "last": last,
                    "change": change,
                    "change_pct": change_pct,
                    "points": points,
                    "as_of": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as exc:
            out.append(
                {
                    "ticker": ticker,
                    "status": "error",
                    "period": period,
                    "error": str(exc)[:120],
                    "as_of": datetime.now(UTC).isoformat(),
                }
            )
    return out


def account_summary(db_path: Path) -> dict[str, Any]:
    """Aggregate snapshot across all brains for the LIVE top metric row."""
    portfolios = brain_portfolio_rows(db_path)
    total_equity = sum(row["equity"] for row in portfolios)
    total_cash = sum(row["cash"] for row in portfolios)
    open_positions = [row for row in portfolios if row["position_qty"] != 0]
    position_value = sum(row["equity"] - row["cash"] for row in portfolios)
    realized_pnl = sum(row["realized_pnl"] for row in portfolios)
    today_change = sum((row["equity"] - row["equity_prior"]) for row in portfolios)
    prior_total = sum(row["equity_prior"] for row in portfolios)
    today_change_pct = (today_change / prior_total * 100.0) if prior_total else 0.0
    return {
        "brain_count": len(portfolios),
        "total_equity": total_equity,
        "total_cash": total_cash,
        "position_value": position_value,
        "open_position_count": len(open_positions),
        "realized_pnl": realized_pnl,
        "today_change": today_change,
        "today_change_pct": today_change_pct,
    }


def live_quotes(tickers: list[str]) -> list[dict[str, Any]]:
    """Best-effort live (15-min-delayed) quotes via yfinance.

    Caller is expected to cache; see apps/dashboard.py for the @st.cache_data
    wrapper that holds these for 30s. Returns one row per ticker. On any
    per-ticker error the row carries `status="error"` so the UI can show that
    instead of crashing.
    """
    try:
        import yfinance  # noqa: F401 — runtime import; optional dep
    except ImportError:
        return [{"ticker": t, "status": "yfinance_missing"} for t in tickers]

    import yfinance as yf

    out: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            info = tk.fast_info
            last = float(info.last_price) if info.last_price is not None else None
            prev_close = float(info.previous_close) if info.previous_close is not None else None
            change = (last - prev_close) if (last is not None and prev_close is not None) else None
            change_pct = (change / prev_close * 100.0) if (change is not None and prev_close) else None
            out.append(
                {
                    "ticker": ticker,
                    "last": last,
                    "prev_close": prev_close,
                    "change": change,
                    "change_pct": change_pct,
                    "currency": getattr(info, "currency", None),
                    "status": "ok" if last is not None else "no_price",
                    "as_of": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as exc:
            out.append(
                {
                    "ticker": ticker,
                    "status": "error",
                    "error": str(exc)[:120],
                    "as_of": datetime.now(UTC).isoformat(),
                }
            )
    return out
