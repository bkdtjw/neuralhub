from __future__ import annotations

from typing import TYPE_CHECKING

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .plan_models import PlanStep, TodoStep

if TYPE_CHECKING:
    from .plan_execute_runner import PlanExecuteRunner

TODOUPDATE_TOOL_NAME = "TodoUpdate"
MAX_TODO_UPDATES = 3
LOCKED_TODO_STATUSES = {"done", "failed", "running"}

TODOUPDATE_DEFINITION = ToolDefinition(
    name=TODOUPDATE_TOOL_NAME,
    description=(
        "更新当前计划的后续步骤。仅在发现当前计划需要调整时使用；"
        "可修改、新增、删除未执行步骤，不可修改已完成或正在执行的步骤。"
    ),
    category="code-analysis",
    parameters=ToolParameterSchema(
        properties={
            "action": {
                "type": "string",
                "enum": ["update", "add", "remove"],
                "description": "操作类型",
            },
            "step_id": {"type": "integer", "description": "update/remove 时必填"},
            "title": {"type": "string", "description": "update/add 时必填"},
            "description": {"type": "string", "description": "update/add 时必填"},
            "after_step_id": {"type": "integer", "description": "add 时的插入位置"},
        },
        required=["action"],
    ),
)


def create_todoupdate_executor(runner: PlanExecuteRunner) -> ToolExecuteFn:
    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            if runner._todo_update_count >= MAX_TODO_UPDATES:
                return _result(f"已达到最大调整次数 ({MAX_TODO_UPDATES})，不再接受更多调整。")
            plan = runner._plan
            todo = runner._todo_state
            if plan is None or todo is None:
                return _result("计划尚未初始化", is_error=True)
            action = str(args.get("action", ""))
            message = _apply_update(runner, args, action)
            if message:
                return _result(message, is_error=True)
            runner._todo_update_count += 1
            plan.version += 1
            runner._plan_store.update_plan(runner._plan_name, plan)
            runner._todo_store.update(runner._session_id, runner._plan_name, todo)
            await runner._notify_renderer(
                "on_steps_updated",
                runner._plan_name,
                [{"id": step.step_id, "title": step.title} for step in plan.steps],
                [
                    {"id": step.id, "title": step.title, "status": step.status}
                    for step in todo.steps
                ],
            )
            return _result(f"计划已更新（第 {runner._todo_update_count} 次调整）")
        except Exception as exc:  # noqa: BLE001
            return _result(str(exc), is_error=True)

    return execute


def _apply_update(runner: PlanExecuteRunner, args: dict[str, object], action: str) -> str:
    if action == "update":
        return _update_step(runner, args)
    if action == "add":
        return _add_step(runner, args)
    if action == "remove":
        return _remove_step(runner, args)
    return f"未知操作: {action}"


def _update_step(runner: PlanExecuteRunner, args: dict[str, object]) -> str:
    step_id = _int_arg(args.get("step_id"))
    if step_id is None:
        return "缺少 step_id"
    plan_step = next((step for step in runner._plan.steps if step.step_id == step_id), None)
    todo_step = next((step for step in runner._todo_state.steps if step.id == step_id), None)
    if plan_step is None:
        return f"步骤 {step_id} 不存在"
    if todo_step is not None and todo_step.status in LOCKED_TODO_STATUSES:
        return f"步骤 {step_id} 已执行或正在执行，不可修改"
    title = str(args.get("title", "")).strip()
    description = str(args.get("description", "")).strip()
    if title:
        plan_step.title = title
        if todo_step is not None:
            todo_step.title = title
    if description:
        plan_step.description = description
    return ""


def _add_step(runner: PlanExecuteRunner, args: dict[str, object]) -> str:
    title = str(args.get("title", "")).strip()
    description = str(args.get("description", "")).strip()
    if not title:
        return "新增步骤必须有 title"
    after_id = _int_arg(args.get("after_step_id")) or runner._current_step_id
    new_id = max((step.step_id for step in runner._plan.steps), default=0) + 1
    plan_step = PlanStep(step_id=new_id, title=title, description=description, tools_hint=[])
    todo_step = TodoStep(id=new_id, title=title, status="pending")
    runner._plan.steps.insert(_insert_index(runner._plan.steps, after_id, "step_id"), plan_step)
    runner._todo_state.steps.insert(
        _insert_index(runner._todo_state.steps, after_id, "id"), todo_step
    )
    return ""


def _remove_step(runner: PlanExecuteRunner, args: dict[str, object]) -> str:
    step_id = _int_arg(args.get("step_id"))
    if step_id is None:
        return "缺少 step_id"
    todo_step = next((step for step in runner._todo_state.steps if step.id == step_id), None)
    if todo_step is not None and todo_step.status in LOCKED_TODO_STATUSES:
        return f"步骤 {step_id} 已执行或正在执行，不可删除"
    runner._plan.steps = [step for step in runner._plan.steps if step.step_id != step_id]
    runner._todo_state.steps = [step for step in runner._todo_state.steps if step.id != step_id]
    return ""


def _insert_index(steps: list[object], after_id: int, field: str) -> int:
    return next(
        (index + 1 for index, step in enumerate(steps) if getattr(step, field) == after_id),
        len(steps),
    )


def _int_arg(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _result(output: str, is_error: bool = False) -> ToolResult:
    return ToolResult(output=output, is_error=is_error)


__all__ = [
    "MAX_TODO_UPDATES",
    "TODOUPDATE_DEFINITION",
    "TODOUPDATE_TOOL_NAME",
    "create_todoupdate_executor",
]
