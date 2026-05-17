from __future__ import annotations

import pytest

from backend.core.s01_agent_loop import (
    PLAN_TRANSITIONS,
    TERMINAL_PHASES,
    PlanExecuteRunner,
    PlanPhase,
    PlanState,
    PlanStore,
    TodoStore,
    transition,
    validate_transition,
)
from backend.core.s01_agent_loop.plan_execute_errors import PlanExecuteError
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter


def test_transition_rejects_terminal_to_recon() -> None:
    with pytest.raises(PlanExecuteError, match="completed → recon"):
        transition(PlanPhase.COMPLETED, PlanPhase.RECON)


def test_transition_allows_idle_to_recon() -> None:
    assert transition(PlanPhase.IDLE, PlanPhase.RECON) == PlanPhase.RECON


def test_all_declared_transitions_validate() -> None:
    for current, target in PLAN_TRANSITIONS:
        assert validate_transition(current, target) is True


def test_terminal_phases_have_no_outgoing_transitions() -> None:
    for current in TERMINAL_PHASES:
        for target in PlanPhase:
            if target != current:
                assert validate_transition(current, target) is False


@pytest.mark.parametrize(
    "phase",
    [
        PlanPhase.RECON,
        PlanPhase.PLANNING,
        PlanPhase.AWAITING_APPROVAL,
        PlanPhase.EXECUTING,
        PlanPhase.PAUSED,
    ],
)
def test_runner_cancel_transitions_non_terminal_phases(tmp_path, phase: PlanPhase) -> None:
    runner = PlanExecuteRunner(
        adapter=MockAdapter(),
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )
    plan_name = f"cancel-{phase.value.replace('_', '-')}"
    runner._state = PlanState(plan_name=plan_name, session_id="test-session", phase=phase)

    runner.cancel()

    assert runner.phase == PlanPhase.CANCELLED
