from __future__ import annotations

from dataclasses import dataclass

from backend.common.logging import get_logger, get_worker_id
from backend.common.metrics import incr
from backend.core.task_queue import CapacitySubmitRequest, QueueSubmitSpec, TaskPayload

from .spawn_agent_governance import validate_dispatch_capacity
from .spawn_agent_support import PreparedTask, SpawnAgentDeps, emit_event

logger = get_logger(component="spawn_agent")


class SpawnAgentStageSubmitError(ValueError):
    pass


@dataclass
class StageEvent:
    runnable: list[PreparedTask]
    reused: list[TaskPayload]
    submitted: list[PreparedTask]
    deps: SpawnAgentDeps


async def submit_stage(to_submit: list[PreparedTask], deps: SpawnAgentDeps) -> None:
    try:
        if hasattr(deps.task_queue, "submit_many_with_capacity"):
            await deps.task_queue.submit_many_with_capacity(
                CapacitySubmitRequest(
                    max_active=deps.sub_agent_policy.max_concurrent,
                    specs=[
                        QueueSubmitSpec(
                            task_id=item.task_id,
                            input_data=item.input_data,
                            timeout_seconds=item.timeout_seconds,
                        )
                        for item in to_submit
                    ],
                )
            )
        else:
            existing = await deps.task_queue.get_children(deps.parent_task_id)
            validate_dispatch_capacity(len(to_submit), existing, deps.sub_agent_policy)
            await _fallback_submit(to_submit, deps)
        await incr("sub_agent_tasks_submitted", len(to_submit))
    except Exception as exc:  # noqa: BLE001
        raise SpawnAgentStageSubmitError(str(exc)) from exc


async def emit_stage_event(event: StageEvent) -> None:
    try:
        if not event.runnable:
            return
        if event.reused:
            await incr("sub_agent_reuses", len(event.reused))
        await emit_event(
            event.deps.event_handler,
            "sub_agent_spawned",
            {
                "source": "spawn",
                "run_id": event.deps.parent_task_id,
                "total": len(event.runnable),
                "submitted": len(event.submitted),
                "reused": len(event.reused),
                "specs": [item.label for item in event.runnable],
                "message": f"正在派生 {len(event.submitted)} 个子 agent 并行处理...",
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise SpawnAgentStageSubmitError(str(exc)) from exc


async def _fallback_submit(to_submit: list[PreparedTask], deps: SpawnAgentDeps) -> None:
    for item in to_submit:
        await deps.task_queue.submit(
            item.task_id,
            item.input_data,
            timeout_seconds=item.timeout_seconds,
        )
        logger.info(
            "sub_agent_task_submitted",
            task_id=item.task_id,
            spec_id=item.label,
            worker_id=get_worker_id(),
        )


__all__ = ["StageEvent", "emit_stage_event", "submit_stage"]
