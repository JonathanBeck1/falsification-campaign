from __future__ import annotations

import contextlib

import structlog

from trader.ingestion.sanitize import sanitize_event_text
from trader.normalization.alpaca_news import alpaca_news_to_events
from trader.normalization.fed import fed_news_to_events
from trader.normalization.finnhub import finnhub_news_to_events
from trader.normalization.sec import sec_news_to_events
from trader.normalization.web import web_news_to_events
from trader.normalization.yahoo import yahoo_news_to_events
from trader.runner import fetch_source_news
from trader.storage.store import Store

log = structlog.get_logger()


def _sanitize_event_in_place(event):
    """Apply sanitizer to title + summary. Returns the (possibly new) event
    plus the merged sanitization-flag list for observability."""
    clean_title, clean_summary, flags = sanitize_event_text(event.title, event.summary)
    if not flags:
        return event, ()
    return event.model_copy(update={"title": clean_title, "summary": clean_summary}), flags


def fetch_and_persist_events(
    *,
    store: Store,
    ticker: str,
    context_tickers: list[str],
    sec_tickers: list[str] | None,
    lookback_days: int | None = None,
    source_tracker=None,
) -> dict[str, int]:
    fetch_kwargs = {"lookback_days": lookback_days}
    if source_tracker is not None:
        fetch_kwargs["heartbeat"] = source_tracker
    by_source = fetch_source_news(ticker, context_tickers, sec_tickers, **fetch_kwargs)

    return persist_source_events(
        store=store,
        by_source=by_source,
        ticker=ticker,
        context_tickers=context_tickers,
        source_tracker=source_tracker,
    )


def persist_source_events(
    *,
    store: Store,
    by_source: dict[str, list],
    ticker: str,
    context_tickers: list[str],
    source_tracker=None,
) -> dict[str, int]:
    events_by_source = {
        "finnhub": finnhub_news_to_events(by_source.get("finnhub", []), ticker=ticker),
        "alpaca_news": alpaca_news_to_events(by_source.get("alpaca_news", []), queried_symbols=context_tickers),
        "yahoo_news": yahoo_news_to_events(by_source.get("yahoo_news", []), queried_tickers=context_tickers),
        "sec_edgar": sec_news_to_events(by_source.get("sec_edgar", [])),
        "fed": fed_news_to_events(by_source.get("fed", [])),
        "web_news": web_news_to_events(by_source.get("web_news", []), queried_tickers=context_tickers),
    }

    # Per-event try/except so one malformed row (bad JSON in model_outputs,
    # unexpected None title, etc.) doesn't abort the whole batch. The fetch
    # side already isolates per-source failures via `_safe_fetch_source`; the
    # persist side needs the same guarantee. Failures are logged and recorded
    # as a system event so they're visible in status / dashboards.
    counts: dict[str, int] = {}
    for source, events in events_by_source.items():
        persisted = 0
        for event in events:
            event, sanitize_flags = _sanitize_event_in_place(event)
            if sanitize_flags:
                # Record an audit row so a reviewer can see which articles
                # had which guards fired before they were persisted.
                with contextlib.suppress(Exception):
                    store.record_event(
                        "info",
                        f"{source}.sanitize",
                        f"{event.event_id}: {','.join(sanitize_flags)}",
                    )
            try:
                store.save_news_event(event)
            except Exception as exc:
                event_id = getattr(event, "event_id", "<unknown>")
                log.warning(
                    "event_persist_failed",
                    source=source,
                    event_id=event_id,
                    error=str(exc),
                )
                # Don't let logging-of-failure mask the original loop iteration.
                with contextlib.suppress(Exception):
                    store.record_event("warn", source, f"persist failed for {event_id}: {exc}")
                continue
            persisted += 1
        counts[source] = persisted
    if source_tracker is not None:
        record_persisted_counts = getattr(source_tracker, "record_persisted_counts", None)
        if record_persisted_counts is not None:
            record_persisted_counts(counts)
    return counts
