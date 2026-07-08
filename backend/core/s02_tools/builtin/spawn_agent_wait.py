from __future__ import annotations

import asyncio
from contextlib import suppress
from time import monotonic

from backend.common.logging import get_logger, get_worker_id
from backend.core.task_queue import TaskPayload, TaskStatus
from backend.core.task_queue_support import WAIT_TIMEOUT_ERROR

from .spawn_agent_support import (
    PreparedTask,
    SpawnAgentDeps,
    _emit_missing_events,
    _poll_progress,
)

logger = get_logger(component="spawn_agent")


async def wait_for_prepared_tasks(
    prepared: list[PreparedTask],
    deps: SpawnAgentDeps,
) -> list[TaskPayload]:
    task_ids = [item.task_id for item in prepared]
    global_timeout = min(max(item.timeout_seconds for item in prepared) * 2.0, 600.0)
    logger.info(
        "sub_agent_wait_start",
        worker_id=get_worker_id(),
        task_ids=task_ids,
        global_timeout=global_timeout,
    )
    observed: set[str] = set()
    started_at = monotonic()
    waiter = asyncio.create_task(
        deps.task_queue.wait_for_tasks(
            task_ids,
            poll_interval=0.5,
            global_timeout=global_timeout,
        )
    )
    try:
        while True:
            await _poll_progress(prepared, observed, deps)
            if waiter.done():
                statuses = await waiter
                await _emit_missing_events(prepared, statuses, observed, deps)
                _log_wait_result(prepared, statuses, started_at)
                return statuses
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        # 父任务被取消：联动取消已提交到队列/正在 sub_worker 运行的子任务，避免它们继续占用 worker。
        await _cancel_prepared(prepared, deps)
        raise
    finally:
        if not waiter.done():
            waiter.cancel()
            with suppress(asyncio.CancelledError):
                await waiter


async def _cancel_prepared(prepared: list[PreparedTask], deps: SpawnAgentDeps) -> None:
    for item in prepared:
        with suppress(Exception):
            await deps.task_queue.cancel(item.task_id)


def _log_wait_result(
    prepared: list[PreparedTask],
    statuses: list[TaskPayload],
    started_at: float,
) -> None:
    task_ids = [item.task_id for item in prepared]
    succeeded = sum(1 for status in statuses if status.status == TaskStatus.SUCCEEDED)
    failed = sum(1 for status in statuses if status.status == TaskStatus.FAILED)
    stuck_tasks = [status.task_id for status in statuses if status.error == WAIT_TIMEOUT_ERROR]
    if stuck_tasks:
        logger.error(
            "sub_agent_wait_timeout",
            worker_id=get_worker_id(),
            task_ids=task_ids,
            stuck_tasks=stuck_tasks,
        )
    logger.info(
        "sub_agent_wait_end",
        worker_id=get_worker_id(),
        total=len(prepared),
        succeeded=succeeded,
        failed=failed,
        duration_ms=int((monotonic() - started_at) * 1000),
    )
