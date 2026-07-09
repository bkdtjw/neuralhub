from __future__ import annotations

import asyncio
from contextlib import suppress
from time import monotonic
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.metrics import record_latency_sample
from backend.common.prometheus_metrics import observe_sub_agent_task
from backend.common.tracing import trace_span
from backend.core.s05_skills import AgentRuntime
from backend.core.task_queue import TaskPayload, TaskQueue
from backend.core.task_queue_cancel import PARENT_CANCELLED_ERROR
from backend.storage import SessionStore

from . import task_queue_consumer_helpers as helpers
from .task_queue_agent_failures import AgentFailureReport, fail_agent_payload
from .task_queue_consumer_governance import (
    apply_child_loop_budget,
    build_sub_agent_complete_result,
    enforce_child_loop_permission,
)

logger = get_logger(component="sub_agent_consumer")
HEARTBEAT_INTERVAL_SECONDS, LEASE_EXTENSION_SECONDS = 15.0, 60.0


async def execute_agent_payload(
    payload: TaskPayload,
    queue: TaskQueue,
    runtime: AgentRuntime,
) -> None:
    timeout_seconds = helpers._timeout_seconds(payload.input_data)
    started_at = monotonic()
    cancel_event = asyncio.Event()
    try:
        await _run_agent_payload(payload, queue, runtime, timeout_seconds, started_at, cancel_event)
    except asyncio.CancelledError:
        # C5：父任务取消经心跳置 cancel_event 并 cancel run_task；兑现为协作式失败而非静默中断。
        if not cancel_event.is_set():
            raise
        await helpers._safe_fail(queue, payload.task_id, PARENT_CANCELLED_ERROR, payload.worker_id)
        logger.warning(
            "sub_agent_task_cancelled",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
        )
    except TimeoutError:
        error = f"子 agent 执行超时（{timeout_seconds}s）"
        await fail_agent_payload(AgentFailureReport(payload, queue, error, started_at))
    except Exception as exc:  # noqa: BLE001
        error = f"子 agent 执行失败：{exc}"
        await fail_agent_payload(AgentFailureReport(payload, queue, error, started_at, exc))


async def _run_agent_payload(
    payload: TaskPayload,
    queue: TaskQueue,
    runtime: AgentRuntime,
    timeout_seconds: float,
    started_at: float,
    cancel_event: asyncio.Event,
) -> None:
    spec_id = str(payload.input_data.get("spec_id", ""))
    role = str(payload.input_data.get("role", ""))
    with trace_span("sub_agent.task", {"task_id": payload.task_id, "spec_id": spec_id, "role": role}):
        logger.info(
            "sub_agent_task_execute_start",
            task_id=payload.task_id,
            payload_worker_id=payload.worker_id,
            spec_id=spec_id,
            role=role,
        )
        loop, restored = await _build_sub_agent_loop(payload, runtime)
        run_input = "请继续之前未完成的任务" if restored else str(payload.input_data.get("input", ""))
        run_task = asyncio.create_task(loop.run(run_input), name=f"sub-agent-run-{payload.task_id}")
        # C5：心跳携带 run_task + cancel_event——检测到父取消即置位并 cancel run_task。
        heartbeat = asyncio.create_task(
            helpers._heartbeat_loop(
                queue,
                payload.task_id,
                HEARTBEAT_INTERVAL_SECONDS,
                LEASE_EXTENSION_SECONDS,
                run_task,
                cancel_event,
            ),
            name=f"sub-agent-heartbeat-{payload.task_id}",
        )
        try:
            result = await asyncio.wait_for(run_task, timeout=timeout_seconds)
            completion = await build_sub_agent_complete_result(loop, result)
            completion["tool_call_count"] = helpers._tool_call_count(loop.messages)
            completed = await queue.complete(payload.task_id, completion, worker_id=payload.worker_id)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
    if not completed:
        error = "子 agent 完成结果写入失败"
        logger.warning(
            "sub_agent_task_complete_discarded",
            task_id=payload.task_id,
            worker_id=payload.worker_id,
            error=error,
        )
        await helpers._safe_fail(queue, payload.task_id, error, payload.worker_id)
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
                provider=str(input_data.get("provider", "")).strip(),
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
                provider=str(input_data.get("provider", "")).strip(),
                workspace=workspace,
                session_id=session_id,
                is_sub_agent=True,
                checkpoint_fn=_checkpoint,
            )
        apply_child_loop_budget(loop, input_data)
        enforce_child_loop_permission(loop, input_data)
        await _ensure_session(store, session_id, workspace, loop)
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


async def _ensure_session(
    store: SessionStore,
    session_id: str,
    workspace: str,
    loop: Any,
) -> None:
    await store.ensure_session(
        session_id,
        model=helpers._loop_config_value(loop, "model"),
        provider=helpers._loop_config_value(loop, "provider"),
        system_prompt=helpers._loop_config_value(loop, "system_prompt"),
        workspace=workspace,
    )


__all__ = ["_build_sub_agent_loop", "execute_agent_payload"]
