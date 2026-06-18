"""Scheduler wiring tests."""

from __future__ import annotations


def test_scheduler_registers_daily_market_close_job(monkeypatch):
    from trader import scheduler

    calls = {}

    class FakeBlockingScheduler:
        def __init__(self, *, timezone: str) -> None:
            calls["timezone"] = timezone

        def add_job(self, func, *, trigger, id, name, replace_existing):
            calls["job_func"] = func
            calls["trigger"] = trigger
            calls["id"] = id
            calls["name"] = name
            calls["replace_existing"] = replace_existing

        def start(self):
            calls["started"] = True

    class FakeCronTrigger:
        def __init__(self, **kwargs) -> None:
            calls["trigger_kwargs"] = kwargs

    monkeypatch.setattr(scheduler, "BlockingScheduler", FakeBlockingScheduler)
    monkeypatch.setattr(scheduler, "CronTrigger", FakeCronTrigger)

    scheduler.main()

    assert calls["timezone"] == "America/New_York"
    assert calls["id"] == "trader_daily_run"
    assert calls["name"] == "Trader daily run"
    assert calls["replace_existing"] is True
    assert calls["started"] is True
    assert calls["trigger_kwargs"] == {
        "day_of_week": "mon-fri",
        "hour": 16,
        "minute": 15,
        "timezone": "America/New_York",
    }
