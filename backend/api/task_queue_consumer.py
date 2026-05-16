from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import bound_log_context, get_logger, get_worker_id
from backend.core.s05_skills import AgentRuntime
from backend.core.task_queue import TaskPayload, TaskQueue
from backend.storage import SessionStore

from .task_queue_consumer_helpers import (
    _heartbeat_loop,
    _loop_config_value,
    _restored_messages,
    _safe_fail,
    _timeout_seconds,
    _tool_call_count,
)

logger = get_logger(component="sub_agent_consumer")
HEARTBEAT_INTERVAL_SECONDS = 15.0
LEASE_EXTENSION_SECONDS = 60.0
RESTORE_CONTINUE_PROMPT = "请继续之前未完成的任务"


@dataclass
class SubAgentConsumerContext:
    queue: TaskQueue
    runtime: AgentRuntime


async def consume_next_sub_agent_task(context: SubAgentConsumerContext) -> bool:
    try:
        payload = await context.queue.claim(get_worker_id())
        if payload is None:
            return False
        with bound_log_context(**_payload_log_context(payload)):
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
    timeout_seconds = _timeout_seconds(payload.input_data)
    started_at = monotonic()
    heartbeat = asyncio.create_task(
        _heartbeat_loop(
            context.queue,
            payload.task_id,
            interval=HEARTBEAT_INTERVAL_SECONDS,
            extension=LEASE_EXTENSION_SECONDS,
        ),
        name=f"sub-agent-heartbeat-{payload.task_id}",
    )
    try:
        logger.info(
            "sub_agent_task_execute_start",
            task_id=payload.task_id,
            payload_worker_id=payload.worker_id,
            spec_id=str(payload.input_data.get("spec_id", "")),
            role=str(payload.input_data.get("role", "")),
        )
        loop, restored = await _build_sub_agent_loop(payload, context.runtime)
        run_input = RESTORE_CONTINUE_PROMPT if restored else str(payload.input_data.get("input", ""))
        result = await asyncio.wait_for(loop.run(run_input), timeout=timeout_seconds)
        completed = await context.queue.complete(
            payload.task_id,
            {
                "content": getattr(result, "content", "") or str(result),
                "tool_call_count": _tool_call_count(loop.messages),
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
        logger.info(
            "sub_agent_task_completed",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
            status="succeeded",
            duration_ms=int((monotonic() - started_at) * 1000),
        )
    except TimeoutError:
        error = f"子 agent 执行超时（{timeout_seconds}s）"
        await _safe_fail(context.queue, payload.task_id, error, payload.worker_id)
        logger.error(
            "sub_agent_task_failed",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
            error=error,
            duration_ms=int((monotonic() - started_at) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        error = f"子 agent 执行失败：{exc}"
        await _safe_fail(context.queue, payload.task_id, error, payload.worker_id)
        logger.exception(
            "sub_agent_task_failed",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
            error=error,
            duration_ms=int((monotonic() - started_at) * 1000),
        )
    finally:
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
            model=_loop_config_value(loop, "model"),
            provider=_loop_config_value(loop, "provider"),
            system_prompt=_loop_config_value(loop, "system_prompt"),
            workspace=workspace,
        )
        if payload.retry_count > 0:
            existing = await store.get_messages(session_id)
            if existing:
                loop.message_history.restore(_restored_messages(loop, existing))
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


def _payload_log_context(payload: TaskPayload) -> dict[str, str]:
    return {
        "trace_id": str(payload.input_data.get("trace_id", "")),
        "session_id": f"sub-agent:{payload.task_id}",
        "parent_task_id": payload.parent_task_id,
    }


__all__ = [
    "SubAgentConsumerContext",
    "consume_next_sub_agent_task",
    "execute_sub_agent_task",
]
