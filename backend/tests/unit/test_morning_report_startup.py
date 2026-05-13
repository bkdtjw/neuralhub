from __future__ import annotations

import pytest

from backend.api.morning_report_startup import start_morning_report_cron


@pytest.mark.asyncio
async def test_startup_registers_morning_cron_jobs() -> None:
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
        await scheduler.stop()
