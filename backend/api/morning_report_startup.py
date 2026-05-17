from __future__ import annotations

from pathlib import Path

from backend.config import settings
from backend.core.s07_task_system.cron_scheduler import CronScheduler
from backend.core.s07_task_system.tasks import (
    HealthCheckConfig,
    HealthCheckDeps,
    MorningReportConfig,
    MorningReportDeps,
    run_health_check,
    run_morning_report,
)


_active_scheduler: CronScheduler | None = None


async def start_morning_report_cron(
    feishu_client: object | None,
    chat_id: str | None = None,
) -> CronScheduler | None:
    global _active_scheduler
    if _active_scheduler is not None:
        return _active_scheduler
    resolved_chat_id = chat_id or settings.morning_report_chat_id
    if feishu_client is None or not resolved_chat_id:
        return None
    user_ids = settings.morning_report_user_ids
    config_dir = Path(settings.morning_report_config_dir)
    scheduler = CronScheduler()

    async def health_check() -> None:
        await run_health_check(
            HealthCheckConfig(user_ids=user_ids, chat_id=resolved_chat_id, config_dir=config_dir),
            HealthCheckDeps(feishu_client=feishu_client),
        )

    async def morning_report() -> None:
        await run_morning_report(
            MorningReportConfig(
                user_id=user_ids[0],
                chat_id=resolved_chat_id,
                config_dir=config_dir,
            ),
            MorningReportDeps(feishu_client=feishu_client),
        )

    scheduler.register("morning_health_2230", "30 22 * * *", health_check)
    scheduler.register("morning_health_0600", "0 6 * * *", health_check)
    scheduler.register("morning_health_0755", "55 7 * * *", health_check)
    scheduler.register("morning_report_0800", "0 8 * * *", morning_report)
    await scheduler.start()
    _active_scheduler = scheduler
    return scheduler


async def stop_morning_report_cron() -> None:
    global _active_scheduler
    if _active_scheduler is None:
        return
    await _active_scheduler.stop()
    _active_scheduler = None


__all__ = ["start_morning_report_cron", "stop_morning_report_cron"]
