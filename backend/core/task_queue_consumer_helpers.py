from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from time import monotonic
from typing import TYPE_CHECKING, Any

from backend.common.logging import get_logger
from backend.common.metrics import record_latency_sample
from backend.common.prometheus_metrics import observe_sub_agent_task
from backend.common.types import Message
from backend.core.task_queue import TaskPayload, TaskQueue

if TYPE_CHECKING:
    from backend.core.task_queue_consumer import SubAgentConsumerContext

logger = get_logger(component="sub_agent_consumer")
HEARTBEAT_INTERVAL_SECONDS, LEASE_EXTENSION_SECONDS = 15.0, 60.0


async def _record_task_failure(
    queue: TaskQueue,
    task_id: str,
    worker_id: str,
    error: str,
    started_at: float,
    *,
    exc_info: bool = False,
) -> None:
    duration_seconds = monotonic() - started_at
    observe_sub_agent_task("error", duration_seconds)
    await record_latency_sample("sub_agent_task", int(duration_seconds * 1000))
    await _safe_fail(queue, task_id, error, worker_id)
    log = logger.exception if exc_info else logger.error
    log(
        "sub_agent_task_failed",
        task_id=task_id,
        worker_id=worker_id,
        error=error,
        duration_ms=int(duration_seconds * 1000),
    )


async def _heartbeat_loop(
    queue: TaskQueue,
    task_id: str,
    interval: float,
    extension: float,
    run_task: asyncio.Task[Any] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await queue.renew_lease(task_id, extension)
            if (
                run_task is not None
                and cancel_event is not None
                and await queue.is_cancel_requested(task_id)
            ):
                cancel_event.set()
                run_task.cancel()
                return
        except Exception as exc:  # noqa: BLE001
            logger.warning("sub_agent_task_heartbeat_error", task_id=task_id, error=str(exc))


async def _run_with_heartbeat(
    context: SubAgentConsumerContext,
    payload: TaskPayload,
    coro_factory: Callable[[], Awaitable[Any]],
    timeout_seconds: float,
) -> None:
    # 用心跳保活任意任务：执行期间周期续约 lease，避免长任务被 recover 误判重入队。
    # timeout_seconds 由调用方给定（知识入库应传 payload.timeout_seconds，勿用恒 120s 的 _timeout_seconds）。
    heartbeat = asyncio.create_task(
        _heartbeat_loop(
            context.queue,
            payload.task_id,
            HEARTBEAT_INTERVAL_SECONDS,
            LEASE_EXTENSION_SECONDS,
        ),
        name=f"heartbeat-{payload.task_id}",
    )
    try:
        await asyncio.wait_for(coro_factory(), timeout=timeout_seconds)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


def _timeout_seconds(input_data: dict[str, Any]) -> float:
    raw_timeout = input_data.get("timeout_seconds", 120)
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        return 120.0
    return timeout_seconds if timeout_seconds > 0 else 120.0


def _tool_call_count(messages: list[Any]) -> int:
    return sum(
        len(message.tool_calls)
        for message in messages
        if getattr(message, "role", "") == "assistant" and getattr(message, "tool_calls", None)
    )


def _loop_config_value(loop: Any, name: str) -> str:
    value = getattr(getattr(loop, "_config", None), name, "")
    return value if isinstance(value, str) else ""


def _restored_messages(loop: Any, messages: list[Message]) -> list[Message]:
    prompt = _loop_config_value(loop, "system_prompt")
    if prompt and (not messages or messages[0].role != "system"):
        return [Message(role="system", content=prompt), *messages]
    return messages


def _payload_log_context(payload: Any) -> dict[str, str]:
    return {
        "trace_id": str(payload.input_data.get("trace_id", "")),
        "session_id": f"sub-agent:{payload.task_id}",
        "parent_task_id": payload.parent_task_id,
    }


async def _safe_fail(queue: TaskQueue, task_id: str, error: str, worker_id: str = "") -> None:
    try:
        failed = await queue.fail(task_id, error, worker_id=worker_id)
        if not failed:
            logger.warning(
                "sub_agent_task_fail_discarded",
                task_id=task_id,
                worker_id=worker_id,
                original_error=error,
            )
    except Exception as fail_exc:  # noqa: BLE001
        logger.error(
            "sub_agent_task_fail_error",
            task_id=task_id,
            original_error=error,
            fail_error=str(fail_exc),
        )


__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "LEASE_EXTENSION_SECONDS",
    "_heartbeat_loop",
    "_loop_config_value",
    "_payload_log_context",
    "_record_task_failure",
    "_restored_messages",
    "_run_with_heartbeat",
    "_safe_fail",
    "_timeout_seconds",
    "_tool_call_count",
]
