from __future__ import annotations

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.core.task_queue_support import TERMINAL_TASK_STATUSES, TaskQueueStore
from backend.core.task_queue_types import TaskStatus

logger = get_logger(component="task_queue")
PARENT_CANCELLED_ERROR = "parent_cancelled"


class TaskQueueError(AgentError):
    pass


def _cancel_key(queue: TaskQueueStore, task_id: str) -> str:
    return f"task:{queue.namespace}:cancel:{task_id}"


async def cancel_payload_task(queue: TaskQueueStore, task_id: str, worker_id: str = "") -> bool:
    try:
        payload = await queue.get_status(task_id)
        if payload is None or payload.status in TERMINAL_TASK_STATUSES:
            return False
        # 无论 PENDING/RUNNING 都先落一个取消标记：即使此刻恰好被 worker claim 走，
        # sub_worker 心跳仍能在下一轮读到标记并主动中止，覆盖 get_status 与 claim 之间的竞态。
        await queue._redis.set(_cancel_key(queue, task_id), "1", ex=queue._task_ttl_seconds)
        if payload.status == TaskStatus.PENDING:
            await queue._redis.lrem(queue._queue_key, 0, task_id)
            await queue._save_payload(
                payload.model_copy(update={"status": TaskStatus.FAILED, "error": PARENT_CANCELLED_ERROR})
            )
            logger.info("task_cancelled_pending", namespace=queue.namespace, task_id=task_id, worker_id=worker_id)
            return True
        logger.info("task_cancel_requested", namespace=queue.namespace, task_id=task_id, worker_id=worker_id)
        return True
    except TaskQueueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TaskQueueError("TASK_QUEUE_CANCEL_ERROR", str(exc)) from exc


async def cancel_flag_active(queue: TaskQueueStore, task_id: str) -> bool:
    try:
        return await queue._redis.get(_cancel_key(queue, task_id)) is not None
    except Exception as exc:  # noqa: BLE001
        raise TaskQueueError("TASK_QUEUE_CANCEL_CHECK_ERROR", str(exc)) from exc


__all__ = ["PARENT_CANCELLED_ERROR", "TaskQueueError", "cancel_flag_active", "cancel_payload_task"]
