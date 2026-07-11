from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from inspect import isawaitable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.common.types import AgentEvent, AgentEventHandler, ToolResult
from backend.core.s05_skills.models import SubAgentPolicy
from backend.core.s05_skills.registry import SpecRegistry
from backend.core.task_queue import TaskPayload, TaskQueue, TaskStatus

from .spawn_agent_result_format import result_content

_TERMINAL_STATUSES = {TaskStatus.SUCCEEDED, TaskStatus.FAILED}
OnDepFailure = Literal["block", "proceed"]


class SpawnAgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    spec_id: str = ""
    role: str = ""
    template: str = ""
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    input: str
    permission: str = "readonly"
    no_cache: bool = False
    required: bool = False
    depends_on: list[str] = Field(default_factory=list)
    on_dep_failure: OnDepFailure = "block"
    timeout_seconds: float | None = None
    max_iterations: int | None = Field(default=None, ge=1)


class SpawnAgentArgs(BaseModel):
    tasks: list[SpawnAgentTask] = Field(default_factory=list)


@dataclass
class SpawnAgentDeps:
    task_queue: TaskQueue
    spec_registry: SpecRegistry
    workspace: str
    model: str = ""
    provider: str = ""
    event_handler: AgentEventHandler | None = None
    parent_task_id: str = ""
    sub_agent_policy: SubAgentPolicy = dataclass_field(default_factory=SubAgentPolicy)


@dataclass
class PreparedTask:
    index: int
    task_id: str
    label: str
    timeout_seconds: float
    input_data: dict[str, object]
    dag_id: str = ""
    depends_on: list[str] = dataclass_field(default_factory=list)
    on_dep_failure: OnDepFailure = "block"
    required: bool = False


def format_result(prepared: list[PreparedTask], statuses: list[TaskPayload]) -> ToolResult:
    status_map = {status.task_id: status for status in statuses}
    success_count = sum(1 for status in statuses if status.status == TaskStatus.SUCCEEDED)
    total_sub_tool_calls = sum(
        (status.result or {}).get("tool_call_count", 0)
        for status in statuses
        if status.status == TaskStatus.SUCCEEDED
    )
    lines = [f"子 agent 执行完成（{success_count}/{len(prepared)} 成功）", ""]
    required_error = False
    for item in prepared:
        status = status_map.get(item.task_id)
        state = status.status.value if status is not None else "failed"
        required_error = required_error or bool(item.required and state != TaskStatus.SUCCEEDED.value)
        lines.extend([f"[{item.index}] {item.label} ({state})", result_content(status), ""])
    lines.append(f"[meta] sub_agent_tool_calls={total_sub_tool_calls}")
    return ToolResult(output="\n".join(lines).strip(), is_error=success_count == 0 or required_error)


async def emit_event(
    event_handler: AgentEventHandler | None,
    event_type: str,
    data: dict[str, object],
) -> None:
    if event_handler is None:
        return
    result = event_handler(AgentEvent(type=event_type, data=data))
    if isawaitable(result):
        await result


async def _poll_progress(
    prepared: list[PreparedTask],
    observed: set[str],
    deps: SpawnAgentDeps,
) -> list[TaskPayload]:
    statuses = [await deps.task_queue.get_status(item.task_id) for item in prepared]
    completed = sum(
        1
        for status in statuses
        if status is not None and status.status in _TERMINAL_STATUSES
    )
    for item, status in zip(prepared, statuses, strict=False):
        if status is None or status.task_id in observed or status.status not in _TERMINAL_STATUSES:
            continue
        observed.add(status.task_id)
        await emit_event(
            deps.event_handler,
            "sub_agent_completed" if status.status == TaskStatus.SUCCEEDED else "sub_agent_failed",
            {
                "source": "spawn",
                "run_id": deps.parent_task_id,
                "task_id": status.task_id,
                "spec_id": item.label,
                "completed": completed,
                "total": len(prepared),
                "error": status.error,
                "message": _progress_message(item.label, completed, len(prepared), status),
            },
        )
    return [status for status in statuses if status is not None]


async def _emit_missing_events(
    prepared: list[PreparedTask],
    statuses: list[TaskPayload],
    observed: set[str],
    deps: SpawnAgentDeps,
) -> None:
    status_map = {status.task_id: status for status in statuses}
    completed = sum(1 for status in statuses if status.status in _TERMINAL_STATUSES)
    for item in prepared:
        status = status_map.get(item.task_id)
        if status is None or status.task_id in observed or status.status not in _TERMINAL_STATUSES:
            continue
        observed.add(status.task_id)
        await emit_event(
            deps.event_handler,
            "sub_agent_completed" if status.status == TaskStatus.SUCCEEDED else "sub_agent_failed",
            {
                "source": "spawn",
                "run_id": deps.parent_task_id,
                "task_id": status.task_id,
                "spec_id": item.label,
                "completed": completed,
                "total": len(prepared),
                "error": status.error,
                "message": _progress_message(item.label, completed, len(prepared), status),
            },
        )


def _progress_message(label: str, completed: int, total: int, status: TaskPayload) -> str:
    if status.status == TaskStatus.SUCCEEDED:
        return f"子 agent {label} 已完成（{completed}/{total}）"
    return f"子 agent {label} 执行失败：{status.error}"


__all__ = ["SpawnAgentArgs", "SpawnAgentDeps", "SpawnAgentTask", "emit_event", "format_result"]
