from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.common.errors import AgentError
from backend.common.types import Message, generate_id
from backend.common.types.llm import LLMRequest

from .plan_checkpoint_store import PlanCheckpointStore
from .plan_control import PlanControlState
from .plan_execute_errors import PlanExecuteError
from .plan_execute_runner_notifications import PlanExecuteRunnerNotificationsMixin
from .plan_execute_runner_state import PlanExecuteRunnerStateMixin, checkpoint_dir_for
from .plan_execute_runner_steps import PlanExecuteRunnerStepsMixin
from .plan_finish import ExitSummaryInput, build_exit_summary_content, plan_status_for_finish
from .plan_models import ExecutionPlan, PlanPhase, PlanState
from .plan_prompt import PlanParseError, build_planning_messages, parse_plan_response
from .plan_recon import ReconInput, run_recon
from .plan_renderer import PlanRenderer
from .plan_resume import PlanResumeMixin
from .plan_state_machine import is_terminal
from .plan_store import PlanStore, TodoStore, generate_plan_name
from .step_result import StepResult, StepResultStore

if TYPE_CHECKING:
    from backend.adapters.base import LLMAdapter
    from backend.core.s02_tools import ToolRegistry
    from backend.core.s02_tools.mcp import BridgeProtocol


class PlanExecuteRunner(
    PlanResumeMixin,
    PlanExecuteRunnerStateMixin,
    PlanExecuteRunnerNotificationsMixin,
    PlanExecuteRunnerStepsMixin,
):
    def __init__(
        self,
        adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        plan_store: PlanStore,
        todo_store: TodoStore,
        renderer: PlanRenderer | None = None,
        session_id: str = "",
        bridge: BridgeProtocol | None = None,
        agent_spec: Any | None = None,
        checkpoint_store: PlanCheckpointStore | None = None,
        owner_id: str = "unknown",
        system_prompt: str = "",
        skill_prompt: str = "",
        step_result_store: StepResultStore | None = None,
        require_confirmation: bool = True,
    ) -> None:
        self._adapter = adapter
        self._tool_registry = tool_registry
        self._plan_store = plan_store
        self._todo_store = todo_store
        self._bridge = bridge
        self._agent_spec = agent_spec
        self._checkpoint_store = checkpoint_store or PlanCheckpointStore(checkpoint_dir_for(todo_store))  # noqa: E501
        self._renderer = renderer
        self._session_id = session_id or generate_id()
        self._owner_id = owner_id or "unknown"
        self._system_prompt = system_prompt
        self._skill_prompt = skill_prompt
        self._steps_dir = Path(getattr(todo_store, "_base_dir", Path("data/todos"))).parent / "steps"  # noqa: E501
        self._step_result_store = step_result_store or StepResultStore(self._steps_dir)
        self._step_results: list[StepResult] = []
        self._state = PlanState(plan_name="", session_id=self._session_id, owner_id=self._owner_id)
        self._cancel_requested = False
        self._control = PlanControlState()
        self._approval_event: asyncio.Event = asyncio.Event()
        self._approval_timeout_seconds: float = 600.0
        self._require_confirmation = require_confirmation
        self._checkpoint_path: Path | None = None
        self._plan_path: Path | None = None
        self._todo_path: Path | None = None
        self._active_step_loop: Any | None = None

    async def run(self, user_message: str) -> Message:
        try:
            self._reset_state(generate_plan_name())
            if not await self._run_from_recon(user_message):
                return self.build_exit_summary()
            return await self._finish_run()
        except AgentError as exc:
            self._state.error_message = exc.message
            self._persist_state()
            raise
        except Exception as exc:
            self._state.error_message = str(exc)
            self._persist_state()
            raise PlanExecuteError("PLAN_EXECUTE_RUN_ERROR", str(exc)) from exc
    def cancel(self) -> None:
        if is_terminal(self._state.phase):
            return
        if self._state.interrupted_at is None:
            self._state.interrupted_at = datetime.now()
        self._cancel_requested = True
        self._set_phase(PlanPhase.CANCELLED)
        self._control.resume()
        self._approval_event.set()

    def approve(self) -> None:
        self._approval_event.set()

    def reject(self, reason: str = "") -> None:
        self._state.error_message = reason or "Plan rejected by user"
        self._cancelled = True
        self._approval_event.set()

    def approve_tool_call(self, tool_call_id: str) -> bool:
        if self._active_step_loop is None:
            return False
        return self._active_step_loop.approve_tool_call(tool_call_id)

    def reject_tool_call(self, tool_call_id: str) -> bool:
        if self._active_step_loop is None:
            return False
        return self._active_step_loop.reject_tool_call(tool_call_id)

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

    @property
    def bridge(self) -> BridgeProtocol | None:
        return self._bridge

    @property
    def agent_spec(self) -> Any | None:
        return self._agent_spec

    async def _run_recon(self, user_message: str) -> ExecutionPlan:
        return await run_recon(ReconInput(self._adapter, self._tool_registry, self._session_id, user_message))  # noqa: E501

    async def _generate_plan(self, user_message: str, recon_report: str = "") -> ExecutionPlan:
        try:
            tool_names = [definition.name for definition in self._tool_registry.list_definitions()]
            messages = build_planning_messages(user_message, tool_names, recon_report)
            errors: list[str] = []
            for _ in range(2):
                request = LLMRequest(model="", messages=messages, temperature=0.3, max_tokens=4096)
                response = await self._adapter.complete(request)
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
        self._persist_state()

    def _finish(self, status: str) -> None:
        if self._todo_state is None:
            return
        self._todo_state.status = status
        date_field = "cancelled_at" if status == "cancelled" else "completed_at"
        next_status = plan_status_for_finish(status)
        if status == "cancelled" and self._state.interrupted_at is None:
            self._state.interrupted_at = datetime.now()
        setattr(self._todo_state, date_field, datetime.now())
        if self._state.phase == next_status:
            self._persist_state()
            self._persist_final_plan()
            return
        self._set_phase(next_status)
        self._persist_final_plan()

    def _plan_ref(self) -> str:
        return (self._plan_path or Path("data/plans") / f"{self._plan_name}.md").as_posix()

    def _todo_ref(self) -> str:
        if self._checkpoint_path is not None:
            return self._checkpoint_path.as_posix()
        filename = f"{self._session_id}-{self._plan_name}.json"
        return (Path("data/plan_checkpoints") / filename).as_posix()
__all__ = ["PlanExecuteRunner"]
