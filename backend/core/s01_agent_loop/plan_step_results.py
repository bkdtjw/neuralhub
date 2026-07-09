from __future__ import annotations

from pathlib import Path

from backend.common.metrics import incr

from .agent_loop import AgentLoop
from .plan_execution_support import default_status_from, extract_step_context
from .plan_models import PlanStep, TodoStep
from .plan_step_artifacts import archive_agent_step, summary_with_archive
from .step_result import StepResult, StepResultStore, StepStatus


def build_step_result(
    todo_step: TodoStep,
    plan_step: PlanStep,
    loop: AgentLoop | None,
    request_id: str,
    steps_dir: Path,
) -> StepResult:
    if loop is None:
        return _result_from_todo(todo_step, plan_step, request_id)
    original_summary = todo_step.output_summary
    result = extract_step_context(todo_step, plan_step, loop, request_id)
    if not result.result_summary and original_summary:
        todo_step.output_summary = original_summary
        result.result_summary = original_summary
    if todo_step.status != "done":
        if original_summary:
            todo_step.output_summary = original_summary
        return result
    archive_path = archive_agent_step(todo_step, loop.messages, steps_dir)
    todo_step.output_summary = summary_with_archive(todo_step.output_summary, archive_path)
    return result


async def persist_step_result(
    store: StepResultStore, session_id: str, plan_name: str, result: StepResult
) -> Path:
    path = store.write(session_id, plan_name, result)
    result.artifact_path = path.as_posix()
    final_path = store.write(session_id, plan_name, result)
    await incr("plan_step_results_persisted")
    return final_path


async def record_step_result(
    results: list[StepResult],
    store: StepResultStore,
    session_id: str,
    plan_name: str,
    todo_step: TodoStep,
    plan_step: PlanStep,
    loop: AgentLoop | None,
    request_id: str,
    steps_dir: Path,
) -> None:
    result = build_step_result(todo_step, plan_step, loop, request_id, steps_dir)
    await persist_step_result(store, session_id, plan_name, result)
    upsert_step_result(results, result)


async def record_step_resumed_from_disk(
    todo_step: TodoStep,
    results: list[StepResult],
) -> None:
    if todo_step.status != "done":
        return
    for result in results:
        if result.step_id == todo_step.id and result.status == StepStatus.DONE:
            await incr("plan_step_resumed_from_disk")
            return


def upsert_step_result(results: list[StepResult], result: StepResult) -> None:
    results[:] = [existing for existing in results if existing.step_id != result.step_id]
    results.append(result)


def _result_from_todo(todo_step: TodoStep, plan_step: PlanStep, request_id: str) -> StepResult:
    return StepResult(
        step_id=todo_step.id,
        request_id=request_id,
        status=default_status_from(todo_step),
        task=plan_step.title,
        result_summary=todo_step.output_summary,
        files_touched=todo_step.files_touched,
        key_findings=todo_step.key_findings,
        duration_s=todo_step.duration_s,
    )


__all__ = [
    "build_step_result",
    "persist_step_result",
    "record_step_result",
    "record_step_resumed_from_disk",
    "upsert_step_result",
]
