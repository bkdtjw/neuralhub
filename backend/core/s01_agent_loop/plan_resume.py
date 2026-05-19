from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from backend.common.types import Message

from .plan_approval_wait import await_plan_approval
from .plan_execute_errors import PlanExecuteError
from .plan_finish import execution_finish_status
from .plan_models import PlanPhase, PlanState, TodoState, TodoStep
from .plan_state_machine import TERMINAL_PHASES

if TYPE_CHECKING:
    from backend.adapters.base import LLMAdapter
    from backend.core.s02_tools import ToolRegistry
    from backend.core.s02_tools.mcp import BridgeProtocol

    from .plan_checkpoint_store import PlanCheckpointStore
    from .plan_execute_runner import PlanExecuteRunner
    from .plan_renderer import PlanRenderer
    from .plan_store import PlanStore, TodoStore
    from .step_result import StepResultStore

class PlanResumeMixin:
    @classmethod
    def resume_from_checkpoint(
        cls,
        checkpoint_store: PlanCheckpointStore,
        session_id: str,
        adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        plan_store: PlanStore,
        todo_store: TodoStore,
        renderer: PlanRenderer | None = None,
        bridge: BridgeProtocol | None = None,
        agent_spec: Any | None = None,
        owner_id: str = "",
        step_result_store: StepResultStore | None = None,
    ) -> PlanExecuteRunner | None:
        state = checkpoint_store.load_latest(session_id)
        if state is None or state.phase in TERMINAL_PHASES:
            return None
        runner = cls(
            adapter,
            tool_registry,
            plan_store,
            todo_store,
            renderer,
            session_id,
            bridge=bridge,
            agent_spec=agent_spec,
            checkpoint_store=checkpoint_store,
            owner_id=owner_id or state.owner_id,
            step_result_store=step_result_store,
        )
        runner._state = state.model_copy(deep=True)
        runner._owner_id = owner_id or runner._state.owner_id
        runner._plan_path = _store_path(plan_store, runner._state.plan_name)
        runner._todo_path = None
        runner._reset_interrupted_steps()
        runner._state.resume_point = f"{runner._state.phase.value}:{_first_pending_step_id(runner._state)}"
        runner._persist_state(persist_plan=runner._state.plan is not None)
        return runner

    def _reset_interrupted_steps(self) -> int:
        todo = self._todo_state
        if todo is None:
            return 0
        reset_count = 0
        for step in todo.steps:
            if step.status == "running":
                step.status = "pending"
                reset_count += 1
        return reset_count

    async def resume_run(self) -> Message:
        try:
            if self._state.phase == PlanPhase.IDLE:
                raise PlanExecuteError("PLAN_RESUME_IDLE", "Cannot resume idle plan")
            if self._state.phase in TERMINAL_PHASES:
                return self.build_exit_summary()
            if self._state.phase in {PlanPhase.RECON, PlanPhase.PLANNING}:
                if not await self._run_from_recon(_resume_goal(self._state)):
                    return self.build_exit_summary()
            elif self._state.phase in {PlanPhase.PLAN_READY, PlanPhase.AWAITING_APPROVAL}:
                if not await self._await_plan_approval():
                    return self.build_exit_summary()
                await self._execute_existing_plan()
            elif self._state.phase in {PlanPhase.EXECUTING, PlanPhase.PAUSED}:
                await self._execute_existing_plan()
            else:
                raise PlanExecuteError("PLAN_RESUME_PHASE_ERROR", self._state.phase.value)
            return await self._finish_run()
        except Exception as exc:
            self._state.error_message = getattr(exc, "message", str(exc))
            self._persist_state()
            if isinstance(exc, PlanExecuteError):
                raise
            raise PlanExecuteError("PLAN_RESUME_RUN_ERROR", str(exc)) from exc

    async def _run_from_recon(self, user_message: str) -> bool:
        if self._state.phase != PlanPhase.RECON:
            self._set_phase(PlanPhase.RECON)
        await self._notify_renderer("on_recon_start", user_message)
        recon_report = await self._run_recon(user_message)
        if self._cancelled:
            return False
        self._state.recon_report = recon_report[:2000]
        self._persist_state()
        await self._notify_renderer("on_recon_done", recon_report[:200])
        self._set_phase(PlanPhase.PLANNING)
        self._plan = await self._generate_plan(user_message, recon_report)
        if self._cancelled:
            return False
        self._persist_state(persist_plan=True)
        self._todo_state = TodoState(
            plan_name=self._plan_name,
            session_id=self._session_id,
            steps=[TodoStep(id=step.step_id, title=step.title) for step in self._plan.steps],
        )
        self._persist_state()
        self._set_phase(PlanPhase.PLAN_READY)
        if self._cancelled:
            return False
        if not await self._await_plan_approval():
            return False
        await self._execute_existing_plan()
        return True

    async def _await_plan_approval(self) -> bool:
        return await await_plan_approval(self)

    async def _execute_existing_plan(self) -> None:
        if self._todo_state is None:
            raise PlanExecuteError("PLAN_RESUME_TODO_MISSING", "Missing todo state")
        if self._state.phase != PlanPhase.EXECUTING:
            self._set_phase(PlanPhase.EXECUTING)
        self._todo_state.status = "executing"
        self._persist_state()
        await self._notify_renderer("on_plan_approved", self._plan_name)
        await self._execute_todo_steps()

    async def _finish_run(self) -> Message:
        try:
            self._finish("cancelled" if self._cancelled else execution_finish_status(self._todo_state))
            await self._notify_finished()
            return self.build_exit_summary()
        finally:
            self._checkpoint_store.cleanup()


def _store_path(store: object, plan_name: str) -> Path | None:
    path_for = getattr(store, "_path_for", None)
    return path_for(plan_name) if callable(path_for) and plan_name else None


def _first_pending_step_id(state: PlanState) -> int:
    if state.todo is None:
        return 0
    for step in state.todo.steps:
        if step.status == "pending":
            return step.id
    return 0


def _resume_goal(state: PlanState) -> str:
    if state.plan is not None and state.plan.goal:
        return state.plan.goal
    return state.recon_report or state.plan_name or "resume plan"


__all__ = ["PlanResumeMixin"]
