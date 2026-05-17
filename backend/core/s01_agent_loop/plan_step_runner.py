from __future__ import annotations

import asyncio
from typing import Any

from .plan_convergence import ConvergenceMonitor
from .plan_execute_errors import PlanExecuteError
from .plan_models import PlanStep, TodoStep
from .plan_script_step import execute_script_step
from .plan_step_artifacts import archive_script_step, summary_with_archive
from .plan_step_checkpoint import adapter_provider_name, prepare_step_checkpoint


async def run_agent_step(runner: Any, todo_step: TodoStep, context: Any, timeout: float) -> None:
    loop = runner._build_step_loop(todo_step, context)
    runner._active_step_loop = loop
    runner._persist_state()
    await prepare_step_checkpoint(loop, todo_step, adapter_provider_name(getattr(runner, "_adapter", None)))
    monitor = ConvergenceMonitor(loop, _step_goal(context))
    loop.on(monitor.on_event)
    _, user_message = runner._build_step_prompt(context)
    await asyncio.wait_for(loop.run(user_message), timeout=timeout)
    runner._extract_step_context(todo_step, loop)


async def run_script_step(runner: Any, todo_step: TodoStep, plan_step: PlanStep) -> None:
    result = await execute_script_step(plan_step, runner._tool_registry)
    path = archive_script_step(todo_step, result, runner._steps_dir)
    todo_step.output_summary = summary_with_archive(result.output, path)
    todo_step.key_findings = [result.output.splitlines()[0][:200]] if result.output else []
    if result.is_error:
        raise PlanExecuteError("PLAN_SCRIPT_STEP_FAILED", result.output[:500])


async def notify_step_finished(runner: Any, todo_step: TodoStep) -> None:
    if runner._renderer is None:
        return
    if todo_step.status == "done":
        await runner._notify_renderer("on_step_done", todo_step.id, todo_step.title, todo_step.duration_s, todo_step.output_summary[:200])
    elif todo_step.status == "failed":
        await runner._notify_renderer("on_step_failed", todo_step.id, todo_step.title, todo_step.output_summary[:200])


__all__ = ["notify_step_finished", "run_agent_step", "run_script_step"]


def _step_goal(context: Any) -> str:
    return f"{context.plan_step.title}\n{context.plan_step.description}".strip()
