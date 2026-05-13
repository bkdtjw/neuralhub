from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="cron_scheduler")


class CronSchedulerConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timezone: str = "Asia/Shanghai"
    check_interval: float = Field(default=30.0, ge=0.01)
    now_fn: Callable[[], datetime] | None = None
    sleep_fn: Callable[[float], Awaitable[None]] | None = None


class CronJob(BaseModel):
    name: str
    expression: str
    next_fire_at: datetime


class _CronEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    job: CronJob
    callback: Callable[[], Awaitable[None]]


class CronScheduler:
    def __init__(self, config: CronSchedulerConfig | None = None) -> None:
        self._config = config or CronSchedulerConfig()
        self._timezone = ZoneInfo(self._config.timezone)
        self._jobs: dict[str, _CronEntry] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def register(
        self,
        name: str,
        expression: str,
        callable: Callable[[], Awaitable[None]],
        *,
        replace: bool = False,
    ) -> None:
        try:
            if name in self._jobs and not replace:
                raise AgentError("CRON_JOB_DUPLICATE", f"Cron job already registered: {name}")
            next_fire_at = self._next_fire(expression, self._now())
            self._jobs[name] = _CronEntry(
                job=CronJob(name=name, expression=expression, next_fire_at=next_fire_at),
                callback=callable,
            )
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AgentError("CRON_REGISTER_ERROR", str(exc)) from exc

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("cron_scheduler_started", job_count=len(self._jobs))

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("cron_scheduler_cancelled")
            self._task = None
        logger.info("cron_scheduler_stopped")

    def list_jobs(self) -> list[CronJob]:
        return [entry.job for entry in self._jobs.values()]

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.error("cron_scheduler_loop_error", error=str(exc))
            await self._sleep(self._config.check_interval)

    async def _tick(self) -> None:
        now = self._now()
        for entry in list(self._jobs.values()):
            if entry.job.next_fire_at > now:
                continue
            await self._run_job(entry)
            entry.job.next_fire_at = self._next_fire(entry.job.expression, now)

    async def _run_job(self, entry: _CronEntry) -> None:
        try:
            logger.info("cron_job_triggered", name=entry.job.name)
            await entry.callback()
        except Exception as exc:  # noqa: BLE001
            logger.error("cron_job_failed", name=entry.job.name, error=str(exc))

    def _next_fire(self, expression: str, after: datetime) -> datetime:
        base = (
            after.astimezone(self._timezone)
            if after.tzinfo
            else after.replace(tzinfo=self._timezone)
        )
        next_fire = croniter(expression, base).get_next(datetime)
        return next_fire if next_fire.tzinfo else next_fire.replace(tzinfo=self._timezone)

    def _now(self) -> datetime:
        value = self._config.now_fn() if self._config.now_fn else datetime.now(self._timezone)
        return (
            value.astimezone(self._timezone)
            if value.tzinfo
            else value.replace(tzinfo=self._timezone)
        )

    async def _sleep(self, seconds: float) -> None:
        if self._config.sleep_fn is not None:
            await self._config.sleep_fn(seconds)
            return
        await asyncio.sleep(seconds)


__all__ = ["CronJob", "CronScheduler", "CronSchedulerConfig"]
