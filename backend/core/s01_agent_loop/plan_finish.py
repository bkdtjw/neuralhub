from __future__ import annotations

from dataclasses import dataclass

from .plan_execution_support import SUMMARY_DISPLAY_LIMIT
from .plan_models import ExecutionPlan, PlanPhase, TodoState


def execution_finish_status(todo_state: TodoState | None) -> str:
    if todo_state is None:
        return "completed"
    failed_count = sum(1 for step in todo_state.steps if step.status == "failed")
    return "partial_failed" if failed_count else "completed"


def plan_status_for_finish(status: str) -> PlanPhase:
    if status == "cancelled":
        return PlanPhase.CANCELLED
    if status == "partial_failed":
        return PlanPhase.PARTIAL_FAILED
    return PlanPhase.COMPLETED


@dataclass(frozen=True)
class ExitSummaryInput:
    plan_name: str
    plan: ExecutionPlan | None
    todo_state: TodoState
    plan_ref: str
    todo_ref: str


def build_exit_summary_content(summary_input: ExitSummaryInput) -> str:
    goal = summary_input.plan.goal if summary_input.plan is not None else ""
    lines = [
        f"Plan: {summary_input.plan_name}",
        f"Goal: {goal}",
        f"Status: {summary_input.todo_state.status}",
        "",
    ]
    for step in summary_input.todo_state.steps:
        files = ", ".join(step.files_touched) if step.files_touched else "none"
        lines.append(
            f"{step_status_icon(step.status)} Step {step.id}: {step.title} ({step.status})"
        )
        lines.append(f"Files: {files}")
        if step.key_findings:
            lines.append("Findings: " + "; ".join(step.key_findings))
        if step.output_summary:
            lines.append(f"Summary: {step.output_summary[:SUMMARY_DISPLAY_LIMIT]}")
    lines.extend(
        ["", "Files:", f"- Plan: {summary_input.plan_ref}", f"- Todo: {summary_input.todo_ref}"]
    )
    return "\n".join(lines)


def step_status_icon(status: str) -> str:
    if status == "done":
        return "✅"
    if status == "failed":
        return "❌"
    if status == "skipped":
        return "⏭"
    return "⬜"


__all__ = [
    "build_exit_summary_content",
    "execution_finish_status",
    "ExitSummaryInput",
    "plan_status_for_finish",
    "step_status_icon",
]
