"""Daily scheduler for the trading pipeline."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from trader.runner import run_one_day

MARKET_TIMEZONE = "America/New_York"

log = structlog.get_logger()


def main() -> None:
    """Run the daily scheduler.

    The v0 daily pipeline is intentionally conservative: one run after the
    regular US equity close, Monday through Friday. Holiday awareness belongs in
    the next scheduler pass once the ingestion/execution split is firmer.
    """
    scheduler = BlockingScheduler(timezone=MARKET_TIMEZONE)
    trigger = CronTrigger(day_of_week="mon-fri", hour=16, minute=15, timezone=MARKET_TIMEZONE)
    scheduler.add_job(
        run_one_day,
        trigger=trigger,
        id="trader_daily_run",
        name="Trader daily run",
        replace_existing=True,
    )
    log.info("scheduler_starting", timezone=MARKET_TIMEZONE, hour=16, minute=15)
    scheduler.start()
