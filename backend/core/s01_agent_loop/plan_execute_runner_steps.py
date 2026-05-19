from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any
from uuid import uuid4

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import AgentConfig, Message
from backend.core.s02_tools import ToolRegistry
from .agent_loop import AgentLoop
from .plan_control_store import PlanControlStore
from .plan_convergence import ConvergenceMonitor
from .plan_execute_errors import PlanExecuteError
from .plan_execution_support import build_step_context, extract_step_context, find_plan_step, refresh_pending_todo_titles
from .plan_models import PlanPhase, TodoStep
from .plan_step_checkpoint import make_step_checkpoint_fn, make_step_session_id
from .plan_step_artifacts import archive_agent_step, summary_with_archive
from .plan_step_runner import notify_step_finished, run_agent_step, run_script_step
from .plan_step_prompt import build_step_messages
from .plan_todo_tool import TODOUPDATE_DEFINITION, TODOUPDATE_TOOL_NAME, create_todoupdate_executor
from .tool_review import ToolReviewContext

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
            logger.warning("plan_reread_failed", plan_name=self._plan_name, step_id=step_id, error=str(exc))

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
                if step.status in {"done", "failed", "skipped"}:
                    index += 1
                    continue
                await self._run_step(step)
                self._apply_control_signal()
                if self._cancelled:
                    self._skip_from(index + 1)
                    return
                self._persist_state()
                index += 1
        except Exception as exc:
            raise PlanExecuteError("PLAN_EXECUTE_STEPS_ERROR", str(exc)) from exc

    async def _wait_if_paused(self) -> None:
        self._apply_control_signal()
        if not self._control.pause_requested:
            return
        self._todo_state.status = "paused"
        self._set_phase(PlanPhase.PAUSED)
        while self._control.pause_requested and not self._cancelled:
            await asyncio.sleep(1)
            self._apply_control_signal()
        if not self._cancelled:
            self._todo_state.status = "executing"
            self._set_phase(PlanPhase.EXECUTING)

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
        self._persist_state()
        await self._execute_step(step)

    async def _execute_step(self, todo_step: TodoStep) -> None:
        started_at = monotonic()
        try:
            total_steps = len(self._todo_state.steps) if self._todo_state is not None else 0
            if self._renderer is not None:
                await self._notify_renderer("on_step_start", todo_step.id, todo_step.title, total_steps)

            context = build_step_context(self._plan, self._todo_state, todo_step)
            if context is None:
                raise PlanExecuteError("PLAN_STEP_NOT_FOUND", f"Missing step {todo_step.id}")

            if context.plan_step.type == "script_step":
                await run_script_step(self, todo_step, context.plan_step)
            else:
                await run_agent_step(self, todo_step, context, STEP_TIMEOUT_SECONDS)
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
            self._active_step_loop = None
            self._current_step_id = 0
            self._persist_state()
            await notify_step_finished(self, todo_step)

    def _build_step_loop(self, todo_step: TodoStep, context: Any) -> AgentLoop:
        step_session_id = make_step_session_id(self._session_id, self._plan_name, todo_step.id)
        todo_step.checkpoint_session_id = step_session_id
        step_prompt, _ = self._build_step_prompt(context, include_instruction=False)
        skill_messages = [
            Message(role="system", content=prompt)
            for prompt in [self._skill_prompt, step_prompt]
            if prompt
        ]
        return AgentLoop(
            config=AgentConfig(
                model="",
                system_prompt=self._system_prompt,
                session_id=step_session_id,
                max_iterations=STEP_MAX_ITERATIONS,
            ),
            adapter=self._adapter,
            tool_registry=self._build_step_registry(),
            checkpoint_fn=make_step_checkpoint_fn(step_session_id),
            owner_id=self._owner_id,
            static_skill_messages=skill_messages,
            tool_review_context=ToolReviewContext(
                plan_goal=self._plan.goal if self._plan is not None else "",
                current_step=f"第 {getattr(context, 'step_index', 0) + 1} 步",
                step_description=getattr(context.plan_step, "description", ""),
            ),
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
            getattr(context, "completed_context", ""),
        )
        instruction = self._control.consume_instruction() if include_instruction else ""
        if instruction:
            user_message += f"\n\n## 用户补充指令\n{instruction}"
        return system_prompt, user_message

    def _extract_step_context(self, todo_step: TodoStep, loop: AgentLoop) -> None:
        plan_step = find_plan_step(self._plan, todo_step.id)
        if plan_step is None:
            raise PlanExecuteError("PLAN_STEP_NOT_FOUND", f"Missing step {todo_step.id}")
        extract_step_context(todo_step, plan_step, loop, uuid4().hex)
        path = archive_agent_step(todo_step, loop.messages, self._steps_dir)
        todo_step.output_summary = summary_with_archive(todo_step.output_summary, path)

    def _reload_plan(self) -> None:
        if self._state.plan is not None:
            self._plan = self._state.plan
            refresh_pending_todo_titles(self._todo_state, self._plan)

__all__ = ["ConvergenceMonitor", "PlanExecuteRunnerStepsMixin"]
