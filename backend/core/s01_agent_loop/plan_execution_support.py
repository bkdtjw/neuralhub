from __future__ import annotations

from dataclasses import dataclass, field

from .plan_extract import (
    KEY_FINDING_LIMIT,
    MAX_KEY_FINDINGS,
    OUTPUT_SUMMARY_LIMIT,
    SUMMARY_DISPLAY_LIMIT,
    _extract_files_touched,
    _extract_key_data,
    _extract_key_findings,
    _extract_output_summary,
)
from .plan_models import ExecutionPlan, PlanStep, TodoState, TodoStep
from .step_result import StepResult, StepStatus


@dataclass(frozen=True)
class StepContext:
    plan_step: PlanStep
    previous_summary: str
    step_index: int
    total_steps: int
    completed_context: str = ""
    previous_results: list[StepResult] = field(default_factory=list)


def find_plan_step(plan: ExecutionPlan | None, step_id: int) -> PlanStep | None:
    if plan is None:
        return None
    return next((step for step in plan.steps if step.step_id == step_id), None)


def build_step_context(
    plan: ExecutionPlan | None,
    todo_state: TodoState | None,
    todo_step: TodoStep,
    step_results: list[StepResult] | None = None,
) -> StepContext | None:
    plan_step = find_plan_step(plan, todo_step.id)
    if plan_step is None or plan is None:
        return None
    index = next((idx for idx, step in enumerate(plan.steps, start=1) if step.step_id == todo_step.id), 1)
    previous_results = list(step_results) if step_results is not None else []
    previous_summary = (
        previous_results[-1].result_summary
        if previous_results
        else previous_done_summary(todo_state, todo_step.id)
    )
    return StepContext(
        plan_step=plan_step,
        previous_summary=previous_summary,
        step_index=index,
        total_steps=len(plan.steps),
        completed_context=build_completed_steps_context(todo_state, todo_step.id),
        previous_results=previous_results,
    )


def previous_done_step(todo_state: TodoState | None, step_id: int) -> TodoStep | None:
    if todo_state is None:
        return None
    prior = [step for step in todo_state.steps if step.id < step_id and step.status == "done"]
    return prior[-1] if prior else None


def previous_done_summary(todo_state: TodoState | None, step_id: int) -> str:
    step = previous_done_step(todo_state, step_id)
    return step.output_summary if step is not None else ""


def build_completed_steps_context(
    todo_state: TodoState | None, current_step_id: int, max_total_chars: int = 2000
) -> str:
    """构建所有已完成步骤的结构化上下文摘要。"""
    if todo_state is None or max_total_chars <= 0:
        return ""
    steps = sorted(
        (step for step in todo_state.steps if step.status == "done" and step.id < current_step_id), key=lambda step: step.id
    )
    if not steps:
        return ""
    full_text = "\n\n".join(_format_completed_step(step) for step in steps)
    if len(full_text) <= max_total_chars:
        return full_text
    recent_start = max(len(steps) - 3, 0)
    blocks = [_format_completed_step_brief(step) if index < recent_start else _format_completed_step(step) for index, step in enumerate(steps)]
    while blocks and len("\n\n".join(blocks)) > max_total_chars:
        blocks.pop(0)
    return "\n\n".join(blocks)


def _format_completed_step(step: TodoStep) -> str:
    summary = step.output_summary.strip()[:300] or "无"
    files = _format_step_values(step.files_touched, ", ")
    findings = _format_step_values(step.key_findings[:MAX_KEY_FINDINGS], "; ")
    return f"### 步骤 {step.id}: {step.title}\n摘要: {summary}\n修改文件: {files}\n关键发现: {findings}"

def _format_completed_step_brief(step: TodoStep) -> str:
    return f"步骤 {step.id}: {step.title} | 文件: {_format_step_values(step.files_touched, ', ')}"

def _format_step_values(values: list[str], separator: str) -> str:
    return separator.join(value for value in values if value) or "无"


def remaining_plan_steps(plan: ExecutionPlan | None, step_id: int) -> list[PlanStep]:
    if plan is None:
        return []
    return [step for step in plan.steps if step.step_id >= step_id]


def refresh_pending_todo_titles(todo_state: TodoState | None, plan: ExecutionPlan | None) -> None:
    if todo_state is None or plan is None:
        return
    titles = {step.step_id: step.title for step in plan.steps}
    for todo_step in todo_state.steps:
        if todo_step.status in {"pending", "running", "skipped"} and todo_step.id in titles:
            todo_step.title = titles[todo_step.id]


def extract_step_context(
    todo_step: TodoStep,
    plan_step: PlanStep,
    loop: object,
    request_id: str,
) -> StepResult:
    messages = loop.messages
    output_summary = _extract_output_summary(messages)
    files_touched = _extract_files_touched(messages)
    key_findings = _extract_key_findings(messages)
    todo_step.output_summary = output_summary
    todo_step.files_touched = files_touched
    todo_step.key_findings = key_findings
    return StepResult(
        step_id=todo_step.id,
        request_id=request_id,
        status=default_status_from(todo_step),
        task=plan_step.title,
        result_summary=output_summary,
        key_data=_extract_key_data(messages),
        files_touched=files_touched,
        key_findings=key_findings,
        duration_s=todo_step.duration_s,
    )


def default_status_from(todo_step: TodoStep) -> StepStatus:
    if todo_step.status == "done":
        return StepStatus.DONE
    if todo_step.status == "skipped":
        return StepStatus.SKIPPED
    if todo_step.status == "blocked":
        return StepStatus.BLOCKED
    return StepStatus.FAILED


def tool_call_count(loop: object) -> int:
    return sum(len(message.tool_calls or []) for message in loop.messages if message.role == "assistant")


__all__ = [
    "KEY_FINDING_LIMIT",
    "MAX_KEY_FINDINGS",
    "OUTPUT_SUMMARY_LIMIT",
    "SUMMARY_DISPLAY_LIMIT",
    "build_completed_steps_context",
    "build_step_context",
    "default_status_from",
    "extract_step_context",
    "find_plan_step",
    "previous_done_step",
    "refresh_pending_todo_titles",
    "remaining_plan_steps",
    "tool_call_count",
]
