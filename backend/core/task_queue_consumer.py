from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from backend.common.errors import AgentError
from backend.common.logging import bound_log_context, get_logger, get_worker_id
from backend.core.s05_skills import AgentRuntime
from backend.core.s13_knowledge.feishu_tasks import (
    execute_knowledge_ingest_batch_task,
    execute_knowledge_ingest_task,
)
from backend.core.s13_knowledge.local_tasks import execute_local_knowledge_ingest_task
from backend.core.task_queue import TaskPayload, TaskQueue
from backend.core.task_queue_agent_runner import execute_agent_payload

from . import task_queue_consumer_helpers as helpers

logger = get_logger(component="sub_agent_consumer")
TaskHandler = Callable[[TaskPayload, TaskQueue], Awaitable[None]]


def default_task_handlers() -> dict[str, TaskHandler]:
    return {
        "knowledge_ingest": execute_knowledge_ingest_task,
        "knowledge_ingest_batch": execute_knowledge_ingest_batch_task,
        "knowledge_ingest_local_batch": execute_local_knowledge_ingest_task,
    }


@dataclass
class SubAgentConsumerContext:
    queue: TaskQueue
    runtime: AgentRuntime
    task_handlers: Mapping[str, TaskHandler] = field(default_factory=default_task_handlers)


async def consume_next_sub_agent_task(context: SubAgentConsumerContext) -> bool:
    try:
        payload = await context.queue.claim(get_worker_id())
        if payload is None:
            return False
        with bound_log_context(**helpers._payload_log_context(payload)):
            logger.info(
                "sub_agent_task_claimed",
                task_id=payload.task_id,
                worker_id=payload.worker_id,
                spec_id=str(payload.input_data.get("spec_id", "")),
                role=str(payload.input_data.get("role", "")),
            )
            await execute_sub_agent_task(payload, context)
        return True
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SUB_AGENT_CONSUMER_CLAIM_ERROR", str(exc)) from exc


async def execute_sub_agent_task(
    payload: TaskPayload,
    context: SubAgentConsumerContext,
) -> None:
    try:
        kind = str(payload.input_data.get("kind", "")).strip()
        if kind:
            handler = context.task_handlers.get(kind)
            if handler is None:
                await helpers._safe_fail(
                    context.queue,
                    payload.task_id,
                    f"不支持的子任务类型：{kind}",
                    payload.worker_id,
                )
                return
            # D2：知识入库纳入心跳保活——执行期持续续约 lease，避免超长批次被 recover 误判重入队。
            # 超时上限取 payload.timeout_seconds（本地批量 3600s），非 _timeout_seconds（kb 恒 120s 会误杀）。
            await helpers._run_with_heartbeat(
                context,
                payload,
                lambda: handler(payload, context.queue),
                payload.timeout_seconds,
            )
            return
        await execute_agent_payload(payload, context.queue, context.runtime)
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SUB_AGENT_CONSUMER_EXECUTE_ERROR", str(exc)) from exc


__all__ = [
    "SubAgentConsumerContext",
    "TaskHandler",
    "consume_next_sub_agent_task",
    "default_task_handlers",
    "execute_sub_agent_task",
]
