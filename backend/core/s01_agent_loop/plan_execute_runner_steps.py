from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import AgentConfig
from backend.core.s02_tools import ToolRegistry

from .agent_loop import AgentLoop
from .plan_control_store import PlanControlStore
from .plan_convergence import ConvergenceMonitor
from .plan_execute_errors import PlanExecuteError
from .plan_execution_support import (
    build_step_context,
    extract_step_context,
    refresh_pending_todo_titles,
)
from .plan_models import PlanStatus, TodoStep
from .plan_step_prompt import build_step_messages
from .plan_todo_tool import TODOUPDATE_DEFINITION, TODOUPDATE_TOOL_NAME, create_todoupdate_executor

STEP_TIMEOUT_SECONDS = 600
STEP_MAX_ITERATIONS = 30

logger = get_logger(component="plan_execute_runner")


class PlanExecuteRunnerStepsMixin:
    def pause(self) -> None:
        self._control.request_pause()
        PlanControlStore().request_pause(self._session_id)

    def resume(self, instruction: str = "") -> None:
        self._control.resume(instruction)
        PlanControlStore().request_resume(self._session_id, instruction)

    def is_paused(self) -> bool:
        return self._control.is_waiting()

    async def _sync_plan_before_step(self, step_id: int) -> None:
        try:
            self._reload_plan()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "plan_reread_failed", plan_name=self._plan_name, step_id=step_id, error=str(exc)
            )

    async def _execute_todo_steps(self) -> None:
        try:
            if self._todo_state is None:
                return
            index = 0
            while index < len(self._todo_state.steps):
                self._apply_control_signal()
                await self._wait_if_paused()
                await self._sync_plan_before_step(self._todo_state.steps[index].id)
                if self._cancelled:
                    self._skip_from(index)
                    return
                step = self._todo_state.steps[index]
                await self._run_step(step)
                self._apply_control_signal()
                if self._cancelled:
                    self._skip_from(index + 1)
                    return
                self._persist_todo()
                index += 1
        except Exception as exc:
            raise PlanExecuteError("PLAN_EXECUTE_STEPS_ERROR", str(exc)) from exc

    async def _wait_if_paused(self) -> None:
        self._apply_control_signal()
        if not self._control.pause_requested:
            return
        self._set_status(PlanStatus.PAUSED)
        self._todo_state.status = "paused"
        self._persist_todo()
        while self._control.pause_requested and not self._cancelled:
            await asyncio.sleep(1)
            self._apply_control_signal()
        if not self._cancelled:
            self._set_status(PlanStatus.EXECUTING)
            self._todo_state.status = "executing"
            self._persist_todo()

    def _apply_control_signal(self) -> None:
        signal = PlanControlStore().read(self._session_id)
        if signal.action == "stop":
            self.cancel()
        elif signal.action == "pause":
            self._control.request_pause()
        elif signal.action == "resume":
            self._control.resume(signal.instruction)
            PlanControlStore().clear(self._session_id)

    async def _run_step(self, step: TodoStep) -> None:
        step.status = "running"
        self._current_step_id = step.id
        self._persist_todo()
        await self._execute_step(step)

    async def _execute_step(self, todo_step: TodoStep) -> None:
        started_at = monotonic()
        try:
            total_steps = len(self._todo_state.steps) if self._todo_state is not None else 0
            if self._renderer is not None:
                await self._notify_renderer(
                    "on_step_start", todo_step.id, todo_step.title, total_steps
                )

            context = build_step_context(self._plan, self._todo_state, todo_step)
            if context is None:
                raise PlanExecuteError("PLAN_STEP_NOT_FOUND", f"Missing step {todo_step.id}")

            loop = self._build_step_loop(todo_step, context)
            monitor = ConvergenceMonitor(loop, _step_goal(context))
            loop.on(monitor.on_event)
            _, user_message = self._build_step_prompt(context)
            await asyncio.wait_for(loop.run(user_message), timeout=STEP_TIMEOUT_SECONDS)
            self._extract_step_context(todo_step, loop)
            todo_step.status = "done"
        except TimeoutError:
            todo_step.status = "failed"
            todo_step.output_summary = "步骤执行超时"
        except AgentError as exc:
            todo_step.status = "failed"
            todo_step.output_summary = exc.message[:500]
        except Exception as exc:  # noqa: BLE001
            todo_step.status = "failed"
            todo_step.output_summary = str(exc)[:500]
        finally:
            todo_step.duration_s = max(round(monotonic() - started_at, 3), 0.001)
            self._current_step_id = 0
            self._persist_todo()
            await self._notify_step_finished(todo_step)

    async def _notify_step_finished(self, todo_step: TodoStep) -> None:
        if self._renderer is None:
            return
        if todo_step.status == "done":
            await self._notify_renderer(
                "on_step_done",
                todo_step.id,
                todo_step.title,
                todo_step.duration_s,
                todo_step.output_summary[:200],
            )
        elif todo_step.status == "failed":
            await self._notify_renderer(
                "on_step_failed",
                todo_step.id,
                todo_step.title,
                todo_step.output_summary[:200],
            )

    def _build_step_loop(self, todo_step: TodoStep, context: Any) -> AgentLoop:
        system_prompt, _ = self._build_step_prompt(context, include_instruction=False)
        return AgentLoop(
            config=AgentConfig(
                model="",
                system_prompt=system_prompt,
                session_id=f"{self._session_id}-plan-{self._plan_name}-step-{todo_step.id}",
                max_iterations=STEP_MAX_ITERATIONS,
            ),
            adapter=self._adapter,
            tool_registry=self._build_step_registry(),
        )

    def _build_step_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for definition in self._tool_registry.list_definitions():
            tool = self._tool_registry.get(definition.name)
            if tool is not None:
                registry.register(definition, tool[1])
        if registry.has(TODOUPDATE_TOOL_NAME):
            registry.remove(TODOUPDATE_TOOL_NAME)
        registry.register(TODOUPDATE_DEFINITION, create_todoupdate_executor(self))
        return registry

    def _build_step_prompt(self, context: Any, include_instruction: bool = True) -> tuple[str, str]:
        system_prompt, user_message = build_step_messages(
            context.plan_step,
            context.step_index,
            context.total_steps,
            context.previous_summary,
        )
        instruction = self._control.consume_instruction() if include_instruction else ""
        if instruction:
            user_message += f"\n\n## 用户补充指令\n{instruction}"
        return system_prompt, user_message

    def _extract_step_context(self, todo_step: TodoStep, loop: AgentLoop) -> None:
        extract_step_context(todo_step, loop)

    def _reload_plan(self) -> None:
        try:
            self._plan = self._plan_store.read_plan(self._plan_name)
            refresh_pending_todo_titles(self._todo_state, self._plan)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_reload_failed", plan_name=self._plan_name, error=str(exc))


def _step_goal(context: Any) -> str:
    return f"{context.plan_step.title}\n{context.plan_step.description}".strip()


__all__ = ["ConvergenceMonitor", "PlanExecuteRunnerStepsMixin"]
