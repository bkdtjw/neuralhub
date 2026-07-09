from __future__ import annotations

from time import time

from backend.common.logging import get_logger
from backend.core.task_queue_support import (
    TaskQueueStore,
    _expire_stale_task,
    _lease_expired,
)
from backend.core.task_queue_types import TaskPayload, TaskStatus

logger = get_logger(component="task_queue")


async def recover_stale_task_payloads(queue: TaskQueueStore) -> int:
    now = time()
    if queue._persistence is not None:
        stale = await queue._persistence.list_stale_running(now)
        checked = len(stale)
    else:
        stale, checked = await _scan_redis_stale(queue, now)
    recovered = 0
    failed = 0
    for payload in stale:
        outcome = await _recover_one_stale(queue, payload)
        if outcome == "recovered":
            recovered += 1
        elif outcome == "failed":
            failed += 1
    _log_stale_scan(queue, checked, recovered, failed)
    return recovered


async def _scan_redis_stale(queue: TaskQueueStore, now: float) -> tuple[list[TaskPayload], int]:
    stale: list[TaskPayload] = []
    checked = 0
    for task_id in await queue._task_ids():
        payload = await queue.get_status(task_id)
        checked += 1
        if payload is None:
            await queue._redis.srem(queue._index_key, task_id)
            continue
        if payload.status == TaskStatus.RUNNING and _lease_expired(payload, now):
            stale.append(payload)
    return stale, checked


async def _recover_one_stale(queue: TaskQueueStore, payload: TaskPayload) -> str:
    if payload.retry_count < payload.max_retries:
        await _requeue_stale_task(queue, payload)
        return "recovered"
    await _expire_stale_task(queue, payload)
    refreshed = await queue.get_status(payload.task_id)
    if refreshed is not None and refreshed.status == TaskStatus.FAILED:
        logger.warning(
            "stale_task_expired",
            namespace=queue.namespace,
            task_id=payload.task_id,
            max_retries=payload.max_retries,
        )
        return "failed"
    return "skipped"


async def _requeue_stale_task(queue: TaskQueueStore, payload: TaskPayload) -> None:
    has_checkpoint = await queue.has_checkpoint(payload.task_id)
    pending = payload.model_copy(
        update={
            "status": TaskStatus.PENDING,
            "worker_id": "",
            "started_at": 0.0,
            "lease_expires_at": 0.0,
            "result": None,
            "error": "",
            "retry_count": payload.retry_count + 1,
        }
    )
    await queue._save_payload(pending)
    await queue._redis.lpush(queue._queue_key, payload.task_id)
    await queue._redis.expire(queue._queue_key, queue._task_ttl_seconds)
    logger.warning(
        "stale_task_recovered",
        namespace=queue.namespace,
        task_id=payload.task_id,
        retry_count=pending.retry_count,
        worker_id=payload.worker_id,
        has_checkpoint=has_checkpoint,
    )


def _log_stale_scan(queue: TaskQueueStore, checked: int, recovered: int, failed: int) -> None:
    if failed:
        log = logger.warning
    elif recovered:
        log = logger.info
    else:
        log = logger.debug
    log(
        "stale_task_scan",
        namespace=queue.namespace,
        checked=checked,
        recovered=recovered,
        failed=failed,
    )


__all__ = ["recover_stale_task_payloads"]
