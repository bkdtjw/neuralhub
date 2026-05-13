from __future__ import annotations

import os

from backend.core.s07_task_system.cron_scheduler import CronScheduler
from backend.core.s07_task_system.tasks import (
    HealthCheckConfig,
    HealthCheckDeps,
    MorningReportConfig,
    MorningReportDeps,
    run_health_check,
    run_morning_report,
)


async def start_morning_report_cron(
    feishu_client: object | None,
    chat_id: str,
) -> CronScheduler | None:
    if feishu_client is None or not chat_id:
        return None
    user_ids = _user_ids()
    scheduler = CronScheduler()

    async def health_check() -> None:
        await run_health_check(
            HealthCheckConfig(user_ids=user_ids, chat_id=chat_id),
            HealthCheckDeps(feishu_client=feishu_client),
        )

    async def morning_report() -> None:
        await run_morning_report(
            MorningReportConfig(user_id=user_ids[0], chat_id=chat_id),
            MorningReportDeps(feishu_client=feishu_client),
        )

    scheduler.register("morning_health_2230", "30 22 * * *", health_check)
    scheduler.register("morning_health_0600", "0 6 * * *", health_check)
    scheduler.register("morning_health_0755", "55 7 * * *", health_check)
    scheduler.register("morning_report_0800", "0 8 * * *", morning_report)
    await scheduler.start()
    return scheduler


def _user_ids() -> list[str]:
    raw = os.getenv("MORNING_REPORT_USER_IDS", "default")
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return values or ["default"]


__all__ = ["start_morning_report_cron"]
