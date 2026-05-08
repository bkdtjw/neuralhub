from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import Message, generate_id
from backend.common.types.llm import LLMRequest

from .plan_control import PlanControlState
from .plan_execute_errors import PlanExecuteError
from .plan_execute_runner_steps import PlanExecuteRunnerStepsMixin
from .plan_finish import (
    ExitSummaryInput,
    build_exit_summary_content,
    execution_finish_status,
    plan_status_for_finish,
)
from .plan_models import ExecutionPlan, PlanStatus, TodoState
from .plan_prompt import PlanParseError, build_planning_messages, parse_plan_response
from .plan_recon import ReconInput, run_recon
from .plan_renderer import PlanRenderer
from .plan_store import PlanStore, TodoStore, generate_plan_name

if TYPE_CHECKING:
    from backend.adapters.base import LLMAdapter
    from backend.core.s02_tools import ToolRegistry

logger = get_logger(component="plan_execute_runner")


class PlanExecuteRunner(PlanExecuteRunnerStepsMixin):
    def __init__(
        self,
        adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        plan_store: PlanStore,
        todo_store: TodoStore,
        renderer: PlanRenderer | None = None,
        session_id: str = "",
    ) -> None:
        self._adapter = adapter
        self._tool_registry = tool_registry
        self._plan_store = plan_store
        self._todo_store = todo_store
        self._renderer = renderer
        self._session_id = session_id or generate_id()
        self._status = PlanStatus.IDLE
        self._plan: ExecutionPlan | None = None
        self._todo_state: TodoState | None = None
        self._plan_name = ""
        self._cancelled = False
        self._control = PlanControlState()
        self._current_step_id = 0
        self._todo_update_count = 0
        self._plan_path: Path | None = None
        self._todo_path: Path | None = None

    @property
    def status(self) -> PlanStatus:
        return self._status

    @property
    def plan_name(self) -> str:
        return self._plan_name

    async def run(self, user_message: str) -> Message:
        try:
            self._plan_name = generate_plan_name()
            self._set_status(PlanStatus.RECON)
            await self._notify_renderer("on_recon_start", user_message)
            recon_report = await self._run_recon(user_message)
            await self._notify_renderer("on_recon_done", recon_report[:200])
            self._set_status(PlanStatus.PLANNING)
            self._plan = await self._generate_plan(user_message, recon_report)
            self._plan_path = self._plan_store.save_plan(self._plan_name, self._plan)
            self._todo_state = self._todo_store.create(
                self._session_id, self._plan_name, self._plan.steps
            )
            self._todo_path = self._todo_store._path_for(self._session_id, self._plan_name)
            self._set_status(PlanStatus.PLAN_READY)
            await self._notify_renderer("on_plan_created", self._plan, self._plan_name)
            self._set_status(PlanStatus.EXECUTING)
            self._todo_state.status = "executing"
            self._persist_todo()
            await self._notify_renderer("on_plan_approved", self._plan_name)
            await self._execute_todo_steps()
            self._finish(
                "cancelled" if self._cancelled else execution_finish_status(self._todo_state)
            )
            await self._notify_finished()
            return self.build_exit_summary()
        except AgentError:
            raise
        except Exception as exc:
            raise PlanExecuteError("PLAN_EXECUTE_RUN_ERROR", str(exc)) from exc

    def cancel(self) -> None:
        self._cancelled = True
        self._control.resume()

    def build_exit_summary(self) -> Message:
        if self._todo_state is None:
            return Message(role="assistant", content="No plan execution has run.")
        content = build_exit_summary_content(
            ExitSummaryInput(
                plan_name=self._plan_name,
                plan=self._plan,
                todo_state=self._todo_state,
                plan_ref=self._plan_ref(),
                todo_ref=self._todo_ref(),
            )
        )
        return Message(role="assistant", content=content)

    def _set_status(self, status: PlanStatus) -> None:
        self._status = status

    async def _notify_renderer(self, method_name: str, *args: object, **kwargs: object) -> None:
        if self._renderer is None:
            return
        try:
            method = getattr(self._renderer, method_name)
            await method(*args, **kwargs)
        except Exception:
            logger.warning("plan_renderer_error", method=method_name, plan_name=self._plan_name)

    async def _notify_finished(self) -> None:
        if self._todo_state is None:
            return
        if self._todo_state.status == "cancelled":
            await self._notify_renderer("on_plan_cancelled", self._plan_name, self._todo_state)
            return
        if self._todo_state.status == "partial_failed":
            done = sum(1 for step in self._todo_state.steps if step.status == "done")
            failed = sum(1 for step in self._todo_state.steps if step.status == "failed")
            await self._notify_renderer(
                "on_plan_partial_failed",
                self._plan_name,
                self._todo_state,
                done,
                failed,
            )
            return
        await self._notify_renderer("on_plan_completed", self._plan_name, self._todo_state)

    async def _run_recon(self, user_message: str) -> str:
        return await run_recon(
            ReconInput(self._adapter, self._tool_registry, self._session_id, user_message)
        )

    async def _generate_plan(self, user_message: str, recon_report: str = "") -> ExecutionPlan:
        try:
            tool_names = [definition.name for definition in self._tool_registry.list_definitions()]
            messages = build_planning_messages(user_message, tool_names, recon_report)
            errors: list[str] = []
            for _ in range(2):
                response = await self._adapter.complete(
                    LLMRequest(model="", messages=messages, temperature=0.3, max_tokens=4096)
                )
                try:
                    return parse_plan_response(response.content)
                except PlanParseError as exc:
                    errors.append(exc.message)
            raise PlanParseError("Planning failed after retry: " + " | ".join(errors))
        except PlanParseError:
            raise
        except Exception as exc:
            raise PlanExecuteError("PLAN_GENERATE_ERROR", str(exc)) from exc

    def _skip_from(self, start: int) -> None:
        if self._todo_state is None:
            return
        for step in self._todo_state.steps[start:]:
            if step.status in {"pending", "running"}:
                step.status = "skipped"
        self._persist_todo()

    def _finish(self, status: str) -> None:
        if self._todo_state is None:
            return
        self._todo_state.status = status
        date_field = "cancelled_at" if status == "cancelled" else "completed_at"
        next_status = plan_status_for_finish(status)
        setattr(self._todo_state, date_field, datetime.now())
        self._set_status(next_status)
        self._persist_todo()

    def _persist_todo(self) -> None:
        if self._todo_state is not None:
            self._todo_store.update(self._session_id, self._plan_name, self._todo_state)

    def _plan_ref(self) -> str:
        path = self._plan_path or Path("data/plans") / f"{self._plan_name}.md"
        return path.as_posix()

    def _todo_ref(self) -> str:
        filename = f"{self._session_id}-plan-{self._plan_name}.json"
        path = self._todo_path or Path("data/todos") / filename
        return path.as_posix()


__all__ = ["PlanExecuteRunner"]
