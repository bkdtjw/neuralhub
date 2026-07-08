from __future__ import annotations
from time import time
from typing import Any

from backend.common.logging import get_log_context, get_logger
from backend.core.task_queue_cancel import TaskQueueError, cancel_flag_active, cancel_payload_task
from backend.core.task_queue_persistence import TaskPersistence
from backend.core.task_queue_recover_support import recover_stale_task_payloads
from backend.core.task_queue_support import update_terminal_payload_state, wait_for_task_payloads
from backend.core.task_queue_types import TaskPayload, TaskStatus

logger = get_logger(component="task_queue")


class TaskQueue:
    def __init__(self, namespace: str, redis_client: Any, task_ttl_seconds: int, claim_block_seconds: int, persistence: TaskPersistence | None = None) -> None:
        self._namespace = namespace
        self._redis = redis_client
        self._task_ttl_seconds = task_ttl_seconds
        self._claim_block_seconds = claim_block_seconds
        self._persistence = persistence

    async def submit(self, task_id: str, input_data: dict[str, Any], timeout_seconds: float = 60.0, max_retries: int = 1) -> TaskPayload:
        try:
            payload_input = _with_log_context(input_data)
            payload = TaskPayload(
                task_id=task_id,
                namespace=self._namespace,
                input_data=payload_input,
                parent_task_id=str(payload_input.get("parent_task_id", "")),
                created_at=time(),
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            await self._save_payload(payload)
            await self._redis.sadd(self._index_key, task_id)
            await self._redis.expire(self._index_key, self._task_ttl_seconds)
            await self._redis.lpush(self._queue_key, task_id)
            await self._redis.expire(self._queue_key, self._task_ttl_seconds)
            logger.info("task_submitted", namespace=self._namespace, task_id=task_id)
            return payload
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_SUBMIT_ERROR", str(exc)) from exc

    async def claim(self, worker_id: str) -> TaskPayload | None:
        try:
            while True:
                item = await self._redis.brpop(self._queue_key, timeout=self._claim_block_seconds)
                if item is None:
                    return None
                task_id = str(item[1])
                if self._persistence is not None:
                    claimed = await self._persistence.claim(task_id, worker_id)
                    if claimed is None:
                        continue
                    await self._cache_payload(claimed)
                    logger.info("task_claimed", namespace=self._namespace, task_id=task_id)
                    return claimed
                payload = await self.get_status(task_id)
                if payload is None or payload.status != TaskStatus.PENDING:
                    continue
                now = time()
                claimed = payload.model_copy(
                    update={
                        "status": TaskStatus.RUNNING,
                        "worker_id": worker_id,
                        "started_at": now,
                        "lease_expires_at": now + payload.timeout_seconds,
                    }
                )
                await self._save_payload(claimed)
                logger.info("task_claimed", namespace=self._namespace, task_id=task_id)
                return claimed
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_CLAIM_ERROR", str(exc)) from exc

    async def complete(self, task_id: str, result: dict[str, Any], worker_id: str = "") -> bool:
        try:
            if self._persistence is not None:
                ok = await self._persistence.complete(task_id, result, worker_id)
                await self._refresh_cache(task_id)
                return ok
            return await update_terminal_payload_state(
                self,
                task_id, TaskStatus.SUCCEEDED, result=result, error="", worker_id=worker_id
            )
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_COMPLETE_ERROR", str(exc)) from exc

    async def fail(self, task_id: str, error: str, worker_id: str = "") -> bool:
        try:
            if self._persistence is not None:
                ok = await self._persistence.fail(task_id, error, worker_id)
                await self._refresh_cache(task_id)
                return ok
            return await update_terminal_payload_state(
                self,
                task_id, TaskStatus.FAILED, result=None, error=error, worker_id=worker_id
            )
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_FAIL_ERROR", str(exc)) from exc

    async def get_status(self, task_id: str) -> TaskPayload | None:
        try:
            if self._persistence is not None:
                payload = await self._persistence.get_status(task_id)
                if payload is not None:
                    await self._cache_payload(payload)
                    return payload
            data = await self._redis.get(self._task_key(task_id))
            return None if data is None else TaskPayload.model_validate_json(str(data))
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_STATUS_ERROR", str(exc)) from exc

    async def wait_for_tasks(self, task_ids: list[str], poll_interval: float = 0.5, global_timeout: float = 0.0) -> list[TaskPayload]:
        try:
            return await wait_for_task_payloads(self, task_ids, poll_interval, global_timeout)
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_WAIT_ERROR", str(exc)) from exc

    async def recover_stale_tasks(self) -> int:
        try:
            return await recover_stale_task_payloads(self)
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_RECOVER_ERROR", str(exc)) from exc

    async def renew_lease(self, task_id: str, extension_seconds: float) -> None:
        try:
            if self._persistence is not None:
                await self._persistence.renew_lease(task_id, extension_seconds)
                await self._refresh_cache(task_id)
        except Exception as exc:  # noqa: BLE001
            raise TaskQueueError("TASK_QUEUE_RENEW_LEASE_ERROR", str(exc)) from exc

    async def has_checkpoint(self, task_id: str) -> bool:
        if self._persistence is None:
            return False
        return await self._persistence.has_checkpoint(task_id)

    async def get_children(self, parent_task_id: str) -> list[TaskPayload]:
        if self._persistence is None or not parent_task_id:
            return []
        return await self._persistence.get_children(parent_task_id)

    async def cancel(self, task_id: str, worker_id: str = "") -> bool:
        return await cancel_payload_task(self, task_id, worker_id)

    async def is_cancel_requested(self, task_id: str) -> bool:
        return await cancel_flag_active(self, task_id)

    async def _save_payload(self, payload: TaskPayload) -> None:
        if self._persistence is not None:
            await self._persistence.save_payload(payload)
        await self._cache_payload(payload)

    async def _cache_payload(self, payload: TaskPayload) -> None:
        await self._redis.set(
            self._task_key(payload.task_id),
            payload.model_dump_json(),
            ex=self._task_ttl_seconds,
        )

    async def _refresh_cache(self, task_id: str) -> None:
        if self._persistence is None:
            return
        payload = await self._persistence.get_status(task_id)
        if payload is not None:
            await self._cache_payload(payload)

    async def _task_ids(self) -> list[str]:
        if self._persistence is not None:
            return await self._persistence.list_task_ids()
        return [str(raw_task_id) for raw_task_id in await self._redis.smembers(self._index_key)]

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def _index_key(self) -> str:
        return f"task:{self._namespace}:index"

    @property
    def _queue_key(self) -> str:
        return f"task:{self._namespace}:queue"

    def _task_key(self, task_id: str) -> str:
        return f"task:{self._namespace}:{task_id}"


def _with_log_context(input_data: dict[str, Any]) -> dict[str, Any]:
    payload_input = dict(input_data)
    context = get_log_context()
    trace_id = str(payload_input.get("trace_id") or context.get("trace_id") or "")
    if trace_id:
        payload_input["trace_id"] = trace_id
    return payload_input


__all__ = ["TaskPayload", "TaskQueue", "TaskQueueError", "TaskStatus"]
