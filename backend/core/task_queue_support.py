from __future__ import annotations

import asyncio
from time import time
from typing import Any, Protocol

from backend.common.logging import get_logger
from backend.core.task_queue_persistence import TaskPersistence
from backend.core.task_queue_types import TaskPayload, TaskStatus

logger = get_logger(component="task_queue")
TERMINAL_TASK_STATUSES = {TaskStatus.SUCCEEDED, TaskStatus.FAILED}
WAIT_TIMEOUT_ERROR = "等待超时，主 agent 放弃等待"


class TaskQueueStore(Protocol):
    namespace: str
    _redis: Any
    _index_key: str
    _queue_key: str
    _task_ttl_seconds: int
    _persistence: TaskPersistence | None

    async def get_status(self, task_id: str) -> TaskPayload | None: ...
    async def fail(self, task_id: str, error: str, worker_id: str = "") -> bool: ...
    async def has_checkpoint(self, task_id: str) -> bool: ...
    async def _save_payload(self, payload: TaskPayload) -> None: ...
    async def _task_ids(self) -> list[str]: ...


async def wait_for_task_payloads(
    queue: TaskQueueStore,
    task_ids: list[str],
    poll_interval: float,
    global_timeout: float,
) -> list[TaskPayload]:
    if not task_ids:
        return []
    deadline = time() + global_timeout if global_timeout > 0 else float("inf")
    while True:
        statuses = [await queue.get_status(task_id) for task_id in task_ids]
        if all(status is not None and status.status in TERMINAL_TASK_STATUSES for status in statuses):
            return [status for status in statuses if status is not None]
        if time() > deadline:
            return await _fail_stuck_tasks(queue, task_ids, statuses)
        await asyncio.sleep(poll_interval)


async def update_terminal_payload_state(
    queue: TaskQueueStore,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any] | None,
    error: str,
    worker_id: str = "",
) -> bool:
    payload = await queue.get_status(task_id)
    if payload is None:
        raise RuntimeError(f"Task not found: {task_id}")
    if payload.status != TaskStatus.RUNNING:
        logger.warning(
            "task_terminal_update_skipped",
            namespace=queue.namespace,
            task_id=task_id,
            current_status=payload.status.value,
            target_status=status.value,
        )
        return False
    if worker_id and payload.worker_id != worker_id:
        logger.warning(
            "task_terminal_update_worker_mismatch",
            namespace=queue.namespace,
            task_id=task_id,
            current_worker_id=payload.worker_id,
            expected_worker_id=worker_id,
        )
        return False
    await queue._save_payload(payload.model_copy(update={"status": status, "result": result, "error": error}))
    return True


def _lease_expired(payload: TaskPayload, now: float) -> bool:
    expires_at = payload.lease_expires_at or (payload.started_at + payload.timeout_seconds)
    return expires_at > 0 and now > expires_at


async def _fail_stuck_tasks(
    queue: TaskQueueStore,
    task_ids: list[str],
    statuses: list[TaskPayload | None],
) -> list[TaskPayload]:
    final_statuses: list[TaskPayload] = []
    for task_id, status in zip(task_ids, statuses, strict=False):
        if status is None:
            continue
        if status.status in TERMINAL_TASK_STATUSES:
            final_statuses.append(status)
            continue
        await _safe_fail(queue, task_id, WAIT_TIMEOUT_ERROR)
        refreshed = await queue.get_status(task_id)
        final_statuses.append(
            refreshed
            if refreshed is not None
            else status.model_copy(update={"status": TaskStatus.FAILED, "error": WAIT_TIMEOUT_ERROR})
        )
    return final_statuses


async def _expire_stale_task(queue: TaskQueueStore, payload: TaskPayload) -> None:
    await _safe_fail(
        queue,
        payload.task_id,
        f"超时重试 {payload.max_retries} 次后仍未完成",
    )


async def _safe_fail(queue: TaskQueueStore, task_id: str, error: str) -> None:
    try:
        await queue.fail(task_id, error)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "stale_task_fail_error",
            namespace=queue.namespace,
            task_id=task_id,
            error=error,
            fail_error=str(exc),
        )
