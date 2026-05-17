from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.common.errors import AgentError
from backend.core.s07_task_system.cron_scheduler import CronScheduler, CronSchedulerConfig


@pytest.mark.asyncio
async def test_cron_scheduler_triggers_and_stops() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    now = {"value": datetime(2026, 5, 13, 7, 59, 0, tzinfo=tz)}
    calls: list[str] = []

    async def sleep_fn(seconds: float) -> None:
        await asyncio.sleep(0)

    async def job() -> None:
        calls.append("run")

    scheduler = CronScheduler(
        CronSchedulerConfig(
            check_interval=0.01,
            now_fn=lambda: now["value"],
            sleep_fn=sleep_fn,
        )
    )
    scheduler.register("minute", "*/1 * * * *", job)
    await scheduler.start()
    now["value"] = datetime(2026, 5, 13, 8, 0, 0, tzinfo=tz)
    await asyncio.sleep(0.05)
    await scheduler.stop()
    count_after_stop = len(calls)
    now["value"] = datetime(2026, 5, 13, 8, 1, 0, tzinfo=tz)
    await asyncio.sleep(0.05)

    assert count_after_stop >= 1
    assert len(calls) == count_after_stop
    assert scheduler.list_jobs()[0].name == "minute"


def test_cron_scheduler_register_replace() -> None:
    async def job() -> None:
        return None

    async def replacement() -> None:
        return None

    scheduler = CronScheduler()
    scheduler.register("daily", "0 8 * * *", job)
    with pytest.raises(AgentError, match="CRON_JOB_DUPLICATE"):
        scheduler.register("daily", "0 9 * * *", replacement)
    scheduler.register("daily", "0 9 * * *", replacement, replace=True)

    [registered] = scheduler.list_jobs()
    assert registered.name == "daily"
    assert registered.expression == "0 9 * * *"
