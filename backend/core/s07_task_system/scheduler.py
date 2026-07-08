from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.common.logging import get_logger
from backend.common.metrics import incr

from .executor import TaskExecutor
from .executor_errors import TaskExecutionError
from .models import ScheduledTask
from .runtime_state import SchedulerRuntimeState
from .schedule_utils import get_next_run_at, get_scheduled_minute_key
from .store import TaskStore

logger = get_logger(component="task_scheduler")


class TaskScheduler:
    def __init__(
        self,
        store: TaskStore,
        executor: TaskExecutor,
        check_interval: float = 30.0,
    ) -> None:
        self._store = store
        self._executor = executor
        self._check_interval = check_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._runtime_state = SchedulerRuntimeState(check_interval)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # 后台补跑错过的任务：串行执行每个错过任务会真跑 LLM agent（每个上限 600s），
        # 若在此 await 会阻塞 FastAPI startup → /health 不通 → K8s 探针杀进程。
        # 去重/运行锁由 _execute_task 的 acquire_running + _should_run 的 is_task_running 保证，
        # 后台 recovery 与 _loop 到点触发不会双跑。存引用防止任务被 GC 回收。
        self._recovery_task = asyncio.create_task(self._recover_missed_tasks())
        self._task = asyncio.create_task(self._loop())
        logger.info("task_scheduler_started", interval=self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass
            self._recovery_task = None
        logger.info("task_scheduler_stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                tasks = await self._store.list_tasks()
                for task in tasks:
                    if task.enabled and await self._should_run(task, now):
                        logger.info("task_triggered", task_id=task.id, task_name=task.name, trigger_type="schedule")
                        await incr("task_triggers")
                        asyncio.create_task(self._execute_task(task, None, "schedule"))
            except Exception:
                logger.exception("task_scheduler_loop_error")
            await asyncio.sleep(self._check_interval)

    async def _should_run(self, task: ScheduledTask, now: datetime) -> bool:
        try:
            minute_key = get_scheduled_minute_key(task, now)
            if minute_key is None:
                return False
            if await self._runtime_state.is_task_running(task.id):
                logger.debug("task_skipped", task_id=task.id, task_name=task.name, reason="already_running")
                return False
            acquired = await self._runtime_state.acquire_trigger(task.id, minute_key)
            if not acquired:
                logger.debug("task_skipped", task_id=task.id, task_name=task.name, reason="cooldown")
            return acquired
        except Exception:
            logger.exception("task_schedule_evaluate_failed", task_id=task.id, task_name=task.name)
            return False

    async def _run_task(self, task: ScheduledTask) -> None:
        await self._execute_task(task, None, "manual")

    async def _execute_task(
        self,
        task: ScheduledTask,
        trigger_minute: str | None,
        trigger_type: str = "manual",
    ) -> None:
        try:
            if not await self._runtime_state.acquire_running(task.id):
                logger.debug("task_skipped", task_id=task.id, task_name=task.name, reason="running_lock_held")
                return
        except Exception:
            logger.exception("task_running_lock_failed", task_id=task.id, task_name=task.name)
            return
        try:
            result = await asyncio.wait_for(
                self._executor.execute(task),
                timeout=600.0,
            )
            await self._store.update_run_status(task.id, "success", result[:500])
            logger.info("task_trigger_completed", task_id=task.id, task_name=task.name, trigger_type=trigger_type, trigger_minute=trigger_minute or "")
        except asyncio.TimeoutError:
            await self._store.update_run_status(task.id, "error", "Execution timed out (10min)")
            await incr("task_failures")
            logger.error("task_execute_timeout", task_id=task.id, task_name=task.name, timeout_seconds=600)
        except TaskExecutionError as exc:
            await self._store.update_run_status(task.id, "error", (exc.output or exc.message)[:500])
            logger.error("task_execute_failed", task_id=task.id, task_name=task.name, error=exc.message)
        except Exception:
            import traceback
            msg = traceback.format_exc()[:500]
            await self._store.update_run_status(task.id, "error", msg)
            logger.exception("task_execute_error", task_id=task.id, task_name=task.name)
        finally:
            try:
                await self._runtime_state.release_running(task.id)
            except Exception:
                logger.exception("task_running_release_failed", task_id=task.id, task_name=task.name)

    async def _recover_missed_tasks(self) -> None:
        try:
            now = datetime.now(timezone.utc)
            tasks = await self._store.list_tasks()
            for task in tasks:
                if not task.enabled or task.last_run_at is None:
                    continue
                if get_next_run_at(task, task.last_run_at) >= now:
                    continue
                try:
                    logger.info("task_missed_recovery", task_id=task.id, task_name=task.name)
                    await incr("task_triggers")
                    await self._execute_task(task, None, "missed_recovery")
                except Exception:
                    logger.exception("task_missed_recovery_failed", task_id=task.id, task_name=task.name)
        except Exception:
            logger.exception("task_missed_recovery_scan_failed")


__all__ = ["TaskScheduler"]
