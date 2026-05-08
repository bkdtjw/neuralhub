from __future__ import annotations

import shlex
from dataclasses import dataclass

from .agent_loop import AgentLoop
from .plan_models import ExecutionPlan, PlanStep, TodoState, TodoStep

OUTPUT_SUMMARY_LIMIT = 4000
SUMMARY_DISPLAY_LIMIT = 200
KEY_FINDING_LIMIT = 200
MAX_KEY_FINDINGS = 5
_PATH_COMMANDS = {"cat", "head", "tail", "less", "more", "nl"}


@dataclass(frozen=True)
class StepContext:
    plan_step: PlanStep
    previous_summary: str
    step_index: int
    total_steps: int


def find_plan_step(plan: ExecutionPlan | None, step_id: int) -> PlanStep | None:
    if plan is None:
        return None
    return next((step for step in plan.steps if step.step_id == step_id), None)


def build_step_context(
    plan: ExecutionPlan | None,
    todo_state: TodoState | None,
    todo_step: TodoStep,
) -> StepContext | None:
    plan_step = find_plan_step(plan, todo_step.id)
    if plan_step is None or plan is None:
        return None
    index = next(
        (idx for idx, step in enumerate(plan.steps, start=1) if step.step_id == todo_step.id),
        1,
    )
    return StepContext(
        plan_step=plan_step,
        previous_summary=previous_done_summary(todo_state, todo_step.id),
        step_index=index,
        total_steps=len(plan.steps),
    )


def previous_done_step(todo_state: TodoState | None, step_id: int) -> TodoStep | None:
    if todo_state is None:
        return None
    prior = [step for step in todo_state.steps if step.id < step_id and step.status == "done"]
    return prior[-1] if prior else None


def previous_done_summary(todo_state: TodoState | None, step_id: int) -> str:
    step = previous_done_step(todo_state, step_id)
    return step.output_summary if step is not None else ""


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


def extract_step_context(todo_step: TodoStep, loop: AgentLoop) -> None:
    messages = loop.messages
    todo_step.output_summary = _extract_output_summary(messages)
    todo_step.files_touched = _extract_files_touched(messages)
    todo_step.key_findings = _extract_key_findings(messages)


def tool_call_count(loop: AgentLoop) -> int:
    return sum(
        len(message.tool_calls or []) for message in loop.messages if message.role == "assistant"
    )


def _extract_output_summary(messages: list[object]) -> str:
    for message in reversed(messages):
        if getattr(message, "role", "") == "assistant":
            content = str(getattr(message, "content", "")).strip()
            if content:
                return content[:OUTPUT_SUMMARY_LIMIT]
    return ""


def _extract_files_touched(messages: list[object]) -> list[str]:
    files: set[str] = set()
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            arguments = getattr(call, "arguments", {}) or {}
            _collect_path_values(arguments, files)
            command = arguments.get("command")
            if isinstance(command, str):
                files.update(_extract_paths_from_command(command))
        for result in getattr(message, "tool_results", None) or []:
            for diff in getattr(result, "diffs", []) or []:
                path = getattr(diff, "path", "")
                if path:
                    files.add(str(path))
    return sorted(files)


def _collect_path_values(value: object, files: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "path" and isinstance(item, str) and item.strip():
                files.add(item.strip())
            else:
                _collect_path_values(item, files)
    elif isinstance(value, list):
        for item in value:
            _collect_path_values(item, files)


def _extract_paths_from_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    paths: list[str] = []
    for index, token in enumerate(tokens):
        if token not in _PATH_COMMANDS:
            continue
        paths.extend(_command_paths_after(tokens[index + 1 :]))
    return paths


def _command_paths_after(tokens: list[str]) -> list[str]:
    paths: list[str] = []
    for token in tokens:
        if token in {"|", "&&", ";"}:
            break
        if token.startswith("-"):
            continue
        paths.append(token)
        if len(paths) >= 2:
            break
    return paths


def _extract_key_findings(messages: list[object]) -> list[str]:
    findings: list[str] = []
    for message in messages:
        for result in getattr(message, "tool_results", None) or []:
            if getattr(result, "is_error", False):
                continue
            first_line = _first_nonempty_line(str(getattr(result, "output", "")))
            if first_line:
                findings.append(first_line[:KEY_FINDING_LIMIT])
            if len(findings) >= MAX_KEY_FINDINGS:
                return findings
    return findings


def _first_nonempty_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


__all__ = [
    "KEY_FINDING_LIMIT",
    "MAX_KEY_FINDINGS",
    "OUTPUT_SUMMARY_LIMIT",
    "SUMMARY_DISPLAY_LIMIT",
    "build_step_context",
    "extract_step_context",
    "find_plan_step",
    "previous_done_step",
    "refresh_pending_todo_titles",
    "remaining_plan_steps",
    "tool_call_count",
]
