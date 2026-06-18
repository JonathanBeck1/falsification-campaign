#!/usr/bin/env python
"""Run the large-move news catalog loop until done or budget hit.

Usage (typically wrapped by scripts/news_catalog_loop.sh):
  TRADER_SEC_USER_AGENT=... ANTHROPIC_API_KEY=... ALPACA_PAPER_KEY_ID=... \
  ALPACA_PAPER_SECRET_KEY=... .venv/bin/python scripts/run_news_catalog.py \
    [--budget-usd 30] [--model claude-sonnet-4-6] [--max-events 5000]

Resumable: events already in the parquet are skipped.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _load_catalog_env() -> None:
    """Load keys from ~/.catalog_env (real values; .env in main repo is placeholders).

    Expected file (chmod 600, never committed):
        ANTHROPIC_API_KEY=sk-ant-api03-...
        ALPACA_PAPER_KEY_ID=...        # optional (news fallback to 8-K only)
        ALPACA_PAPER_SECRET_KEY=...    # optional
        TRADER_SEC_USER_AGENT=name email@example.com   # for SEC EDGAR
    """
    import os
    home = os.path.expanduser("~")
    # Hard-code the working SEC user-agent used elsewhere this session if not set.
    os.environ.setdefault("TRADER_SEC_USER_AGENT", "catalyst-research you@example.com")
    for candidate in (f"{home}/.catalog_env", f"{home}/.anthropic_key"):
        if not os.path.exists(candidate):
            continue
        with open(candidate) as f:
            content = f.read()
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
            else:
                # A single-line file with just the key (.anthropic_key convention).
                os.environ.setdefault("ANTHROPIC_API_KEY", line)


_load_catalog_env()

from trader.catalog.build import (  # noqa: E402
    DEFAULT_THRESHOLD,
    DEFAULT_TICKERS,
    already_classified,
    append_row_atomic,
    classify_one_event,
    detect_events,
    load_catalog,
)

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

CATALOG_PATH = ROOT / "output" / "catalysts" / "news_catalog.parquet"
COMMIT_EVERY = 50          # commit progress every N successful classifications


def _git_commit_progress(n_done: int, n_total: int, spend: float) -> None:
    """Commit the current parquet to the worktree branch."""
    try:
        subprocess.run(
            ["git", "-C", str(ROOT), "add", str(CATALOG_PATH.relative_to(ROOT))],
            check=False, timeout=15,
        )
        subprocess.run(
            ["git", "-C", str(ROOT), "commit", "-q", "-m",
             f"catalog: progress {n_done}/{n_total} events (${spend:.2f} spent)"],
            check=False, timeout=15,
        )
        subprocess.run(
            ["git", "-C", str(ROOT), "push", "origin", "claude/catalyst-edge"],
            check=False, timeout=30,
        )
    except Exception as exc:
        log.warning("catalog_commit_failed", error=str(exc))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-usd", type=float, default=0.0,
                        help="Hard $ budget cap. 0 = unlimited (under Codex sub).")
    parser.add_argument("--model", default="gpt-5.5",
                        help="Codex model (gpt-5.5 default; uses ChatGPT Plus auth).")
    parser.add_argument("--max-events", type=int, default=10000)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--detect-only", action="store_true",
                        help="Just print the event count and exit (no LLM calls).")
    args = parser.parse_args()

    # --- detect events ------------------------------------------------------
    log.info("catalog_detect_start", tickers=DEFAULT_TICKERS, threshold=args.threshold)
    events = detect_events(threshold=args.threshold)
    log.info("catalog_detect_done", n_events=len(events))

    if args.detect_only:
        print(f"Detected {len(events)} events.")
        return 0

    catalog = load_catalog(CATALOG_PATH)
    already = len(catalog)
    log.info("catalog_resume", existing=already)

    # --- iterate ------------------------------------------------------------
    spend = float(catalog["cost_usd"].sum()) if (not catalog.empty and "cost_usd" in catalog) else 0.0
    n_done = 0
    n_skip = 0
    n_err = 0
    pending = [e for e in events if not already_classified(catalog, e.ticker, e.date)]
    log.info("catalog_pending", pending=len(pending), already=already)

    for event in pending:
        if args.budget_usd > 0 and spend >= args.budget_usd:
            log.info("catalog_budget_reached", spend=spend, budget=args.budget_usd)
            break
        if n_done >= args.max_events:
            log.info("catalog_max_events_reached")
            break
        log.info("catalog_iter_start", ticker=event.ticker, date=event.date.isoformat(),
                 ret=round(event.daily_return, 4), spent=round(spend, 3))
        row = classify_one_event(event, model=args.model)
        if row is None:
            n_err += 1
            log.warning("catalog_iter_failed", ticker=event.ticker, date=event.date.isoformat())
            time.sleep(2.0)
            continue
        try:
            append_row_atomic(CATALOG_PATH, row)
        except Exception as exc:
            log.error("catalog_write_failed", error=str(exc))
            n_err += 1
            continue
        spend += float(row["cost_usd"])
        n_done += 1
        if n_done % 10 == 0:
            log.info("catalog_progress", done=n_done, skipped=n_skip, errors=n_err,
                     spent_usd=round(spend, 3), category=row["category"])
        if n_done % COMMIT_EVERY == 0:
            log.info("catalog_committing", done=n_done)
            _git_commit_progress(n_done, len(pending), spend)

    log.info("catalog_finished",
             done=n_done, skipped=n_skip, errors=n_err,
             spent_usd=round(spend, 3),
             finished_at=datetime.now().isoformat(timespec="seconds"))
    # final commit
    if n_done:
        _git_commit_progress(n_done, len(pending), spend)
    return 0 if n_done > 0 or len(pending) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
