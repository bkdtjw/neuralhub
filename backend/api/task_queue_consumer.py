from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any

from backend.api.routes import feishu_knowledge_tasks as kb_tasks
from backend.api.routes import knowledge_local_tasks
from backend.common.errors import AgentError
from backend.common.logging import bound_log_context, get_logger, get_worker_id
from backend.common.metrics import record_latency_sample
from backend.common.prometheus_metrics import observe_sub_agent_task
from backend.common.tracing import trace_span
from backend.core.s05_skills import AgentRuntime
from backend.core.task_queue import TaskPayload, TaskQueue
from backend.core.task_queue_cancel import PARENT_CANCELLED_ERROR
from backend.storage import SessionStore

from . import task_queue_consumer_helpers as helpers

logger = get_logger(component="sub_agent_consumer")
HEARTBEAT_INTERVAL_SECONDS, LEASE_EXTENSION_SECONDS = 15.0, 60.0


@dataclass
class SubAgentConsumerContext:
    queue: TaskQueue
    runtime: AgentRuntime


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


async def execute_sub_agent_task(payload: TaskPayload, context: SubAgentConsumerContext) -> None:
    kind = payload.input_data.get("kind")
    if kind in {"knowledge_ingest", "knowledge_ingest_batch"}:
        task = kb_tasks.execute_knowledge_ingest_task
        if kind == "knowledge_ingest_batch":
            task = kb_tasks.execute_knowledge_ingest_batch_task
        await task(payload, context.queue)
        return
    if kind == "knowledge_ingest_local_batch":
        await knowledge_local_tasks.execute_local_knowledge_ingest_task(payload, context.queue)
        return
    timeout_seconds = helpers._timeout_seconds(payload.input_data)
    started_at = monotonic()
    cancel_event = asyncio.Event()
    heartbeat: asyncio.Task[None] | None = None
    try:
        spec_id = str(payload.input_data.get("spec_id", ""))
        role = str(payload.input_data.get("role", ""))
        with trace_span("sub_agent.task", {"task_id": payload.task_id, "spec_id": spec_id, "role": role}):  # noqa: E501
            logger.info(
                "sub_agent_task_execute_start",
                task_id=payload.task_id,
                payload_worker_id=payload.worker_id,
                spec_id=spec_id,
                role=role,
            )
            loop, restored = await _build_sub_agent_loop(payload, context.runtime)
            run_input = "请继续之前未完成的任务" if restored else str(payload.input_data.get("input", ""))  # noqa: E501
            run_task = asyncio.create_task(loop.run(run_input), name=f"sub-agent-run-{payload.task_id}")  # noqa: E501
            heartbeat = asyncio.create_task(
                helpers._heartbeat_loop(context.queue, payload.task_id, HEARTBEAT_INTERVAL_SECONDS, LEASE_EXTENSION_SECONDS, run_task, cancel_event),  # noqa: E501
                name=f"sub-agent-heartbeat-{payload.task_id}",
            )
            result = await asyncio.wait_for(run_task, timeout=timeout_seconds)
            completed = await context.queue.complete(
                payload.task_id,
                {
                    "content": getattr(result, "content", "") or str(result),
                    "tool_call_count": helpers._tool_call_count(loop.messages),
                },
                worker_id=payload.worker_id,
            )
        if not completed:
            logger.warning(
                "sub_agent_task_complete_discarded",
                task_id=payload.task_id,
                worker_id=payload.worker_id,
            )
            return
        duration_seconds = monotonic() - started_at
        observe_sub_agent_task("success", duration_seconds)
        await record_latency_sample("sub_agent_task", int(duration_seconds * 1000))
        logger.info(
            "sub_agent_task_completed",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
            status="succeeded",
            duration_ms=int(duration_seconds * 1000),
        )
    except asyncio.CancelledError:
        if not cancel_event.is_set():
            raise
        await helpers._safe_fail(context.queue, payload.task_id, PARENT_CANCELLED_ERROR, payload.worker_id)  # noqa: E501
        logger.warning(
            "sub_agent_task_cancelled",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
        )
    except TimeoutError:
        await helpers._record_task_failure(
            context.queue, payload.task_id, payload.worker_id,
            f"子 agent 执行超时（{timeout_seconds}s）", started_at,
        )
    except Exception as exc:  # noqa: BLE001
        await helpers._record_task_failure(
            context.queue, payload.task_id, payload.worker_id,
            f"子 agent 执行失败：{exc}", started_at, exc_info=True,
        )
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


async def _build_sub_agent_loop(
    payload: TaskPayload,
    runtime: AgentRuntime,
) -> tuple[Any, bool]:
    try:
        input_data = payload.input_data
        session_id = f"sub-agent:{payload.task_id}"
        spec_id = str(input_data.get("spec_id", "")).strip()
        workspace = str(input_data.get("workspace", "")).strip()
        store = SessionStore()

        async def _checkpoint(checkpoint_session_id: str, message: Any) -> None:
            await store.add_messages(checkpoint_session_id or session_id, [message])

        if spec_id:
            loop = await runtime.create_loop_from_id(
                spec_id,
                workspace=workspace,
                session_id=session_id,
                is_sub_agent=True,
                checkpoint_fn=_checkpoint,
            )
        else:
            loop = await runtime.create_loop_inline(
                role=str(input_data.get("role", "sub_agent")),
                system_prompt=str(input_data.get("system_prompt", "")),
                tools=[str(name) for name in input_data.get("tools", []) if str(name).strip()],
                model=str(input_data.get("model", "")),
                workspace=workspace,
                session_id=session_id,
                is_sub_agent=True,
                checkpoint_fn=_checkpoint,
            )
        await store.ensure_session(
            session_id,
            model=helpers._loop_config_value(loop, "model"),
            provider=helpers._loop_config_value(loop, "provider"),
            system_prompt=helpers._loop_config_value(loop, "system_prompt"),
            workspace=workspace,
        )
        if payload.retry_count > 0:
            existing = await store.get_messages(session_id)
            if existing:
                loop.message_history.restore(helpers._restored_messages(loop, existing))
                logger.info(
                    "sub_agent_task_checkpoint_restored",
                    task_id=payload.task_id,
                    message_count=len(existing),
                )
                return loop, True
        return loop, False
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SUB_AGENT_LOOP_BUILD_ERROR", str(exc)) from exc

__all__ = ["SubAgentConsumerContext", "consume_next_sub_agent_task", "execute_sub_agent_task"]
