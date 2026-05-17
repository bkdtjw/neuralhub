from __future__ import annotations

import pytest

from backend.api.morning_report_startup import (
    start_morning_report_cron,
    stop_morning_report_cron,
)


@pytest.mark.asyncio
async def test_startup_registers_morning_cron_jobs() -> None:
    await stop_morning_report_cron()
    scheduler = await start_morning_report_cron(object(), "chat")
    assert scheduler is not None
    try:
        names = {job.name for job in scheduler.list_jobs()}
        assert names == {
            "morning_health_2230",
            "morning_health_0600",
            "morning_health_0755",
            "morning_report_0800",
        }
    finally:
        await stop_morning_report_cron()


@pytest.mark.asyncio
async def test_startup_reuses_active_scheduler() -> None:
    await stop_morning_report_cron()
    first = await start_morning_report_cron(object(), "chat")
    second = await start_morning_report_cron(object(), "chat")
    try:
        assert first is not None
        assert first is second
    finally:
        await stop_morning_report_cron()
