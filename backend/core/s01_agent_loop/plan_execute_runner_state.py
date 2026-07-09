from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .plan_control_apply import clear_control_signal
from .plan_models import ExecutionPlan, PlanPhase, PlanState, TodoState
from .plan_state_machine import transition


class PlanExecuteRunnerStateMixin:
    _checkpoint_store: Any
    _checkpoint_path: Path | None
    _owner_id: str
    _plan_path: Path | None
    _plan_store: Any
    _session_id: str
    _state: PlanState
    _todo_path: Path | None
    _todo_store: Any

    @property
    def status(self) -> PlanPhase:
        return self._state.phase

    @property
    def phase(self) -> PlanPhase:
        return self._state.phase

    @property
    def plan_name(self) -> str:
        return self._state.plan_name

    @property
    def _plan_name(self) -> str:
        return self._state.plan_name

    @_plan_name.setter
    def _plan_name(self, value: str) -> None:
        self._state.plan_name = value

    @property
    def _plan(self) -> ExecutionPlan | None:
        return self._state.plan

    @_plan.setter
    def _plan(self, value: ExecutionPlan | None) -> None:
        self._state.plan = value

    @property
    def _todo_state(self) -> TodoState | None:
        return self._state.todo

    @_todo_state.setter
    def _todo_state(self, value: TodoState | None) -> None:
        self._state.todo = value

    @property
    def _current_step_id(self) -> int:
        return self._state.current_step_id

    @_current_step_id.setter
    def _current_step_id(self, value: int) -> None:
        self._state.current_step_id = value

    @property
    def _todo_update_count(self) -> int:
        return self._state.todo_update_count

    @_todo_update_count.setter
    def _todo_update_count(self, value: int) -> None:
        self._state.todo_update_count = value

    @property
    def _cancelled(self) -> bool:
        return bool(getattr(self, "_cancel_requested", False)) or self._state.phase == PlanPhase.CANCELLED

    @_cancelled.setter
    def _cancelled(self, value: bool) -> None:
        self._cancel_requested = bool(value)

    def _reset_state(self, plan_name: str) -> None:
        self._state = PlanState(
            plan_name=plan_name,
            session_id=self._session_id,
            owner_id=self._owner_id,
        )
        self._cancel_requested = False
        self._plan_path = None
        self._todo_path = None
        clear_control_signal(self._session_id)

    def _set_phase(self, phase: PlanPhase) -> None:
        self._state.phase = transition(self._state.phase, phase)
        self._persist_state()

    def _persist_todo(self) -> None:
        self._persist_state()

    def _persist_state(self, *, persist_plan: bool = False, plan_amended: bool = False) -> None:
        _ = persist_plan, plan_amended
        if not self._state.plan_name:
            return
        self._refresh_persisted_fields()
        self._checkpoint_path = self._checkpoint_store.save(self._state)

    def _refresh_persisted_fields(self) -> None:
        self._state.session_id = self._session_id
        self._state.owner_id = self._owner_id
        self._state.resume_point = (
            f"{self._state.phase.value}:{self._state.current_step_id}"
        )
        self._state.updated_at = datetime.now()

    def _persist_final_plan(self) -> None:
        if self._state.plan is None:
            return
        self._plan_path = self._plan_store.save_plan(self._state.plan_name, self._state.plan)


def checkpoint_dir_for(todo_store: Any) -> str | None:
    base_dir = getattr(todo_store, "_base_dir", None)
    if isinstance(base_dir, Path):
        return str(base_dir.parent / "plan_checkpoints")
    return None


__all__ = ["PlanExecuteRunnerStateMixin", "checkpoint_dir_for"]
