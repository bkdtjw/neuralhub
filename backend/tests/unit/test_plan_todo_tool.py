from __future__ import annotations

import asyncio

from backend.core.s01_agent_loop import (
    ExecutionPlan,
    PlanCheckpointStore,
    PlanExecuteRunner,
    PlanStep,
    PlanStore,
    TodoStore,
    TodoState,
    TodoStep,
)
from backend.core.s01_agent_loop.plan_todo_tool import create_todoupdate_executor
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter


def _runner_with_plan(tmp_path) -> PlanExecuteRunner:
    plan = ExecutionPlan(
        goal="test",
        approach=["a"],
        steps=[
            PlanStep(step_id=1, title="done", description="d1"),
            PlanStep(step_id=2, title="pending", description="d2"),
            PlanStep(step_id=3, title="later", description="d3"),
        ],
    )
    runner = PlanExecuteRunner(
        adapter=MockAdapter(),
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )
    runner._plan_name = "test-plan"
    runner._plan = plan
    runner._todo_state = TodoState(
        plan_name=runner._plan_name,
        session_id=runner._session_id,
        steps=[TodoStep(id=step.step_id, title=step.title) for step in plan.steps],
    )
    runner._todo_state.steps[0].status = "done"
    runner._current_step_id = 1
    runner._persist_state()
    return runner


def test_todoupdate_add_step(tmp_path) -> None:
    runner = _runner_with_plan(tmp_path)
    execute = create_todoupdate_executor(runner)
    result = asyncio.run(execute({"action": "add", "title": "new", "description": "new d"}))
    assert result.is_error is False
    assert [step.title for step in runner._plan.steps] == ["done", "new", "pending", "later"]
    assert [step.title for step in runner._todo_state.steps] == ["done", "new", "pending", "later"]
    state = PlanCheckpointStore(str(tmp_path / "plan_checkpoints")).load(
        "test-session", "test-plan"
    )
    assert state is not None
    assert state.plan is not None
    assert [step.title for step in state.plan.steps] == ["done", "new", "pending", "later"]


def test_todoupdate_remove_step(tmp_path) -> None:
    runner = _runner_with_plan(tmp_path)
    execute = create_todoupdate_executor(runner)
    removed = asyncio.run(execute({"action": "remove", "step_id": 2}))
    denied = asyncio.run(execute({"action": "remove", "step_id": 1}))
    assert removed.is_error is False
    assert denied.is_error is True
    assert [step.step_id for step in runner._plan.steps] == [1, 3]


def test_todoupdate_modify_step(tmp_path) -> None:
    runner = _runner_with_plan(tmp_path)
    execute = create_todoupdate_executor(runner)
    result = asyncio.run(
        execute(
            {
                "action": "update",
                "step_id": 2,
                "title": "updated",
                "description": "updated d",
            }
        )
    )
    assert result.is_error is False
    assert runner._plan.steps[1].title == "updated"
    assert runner._plan.steps[1].description == "updated d"
    assert runner._todo_state.steps[1].title == "updated"


def test_todoupdate_max_limit(tmp_path) -> None:
    runner = _runner_with_plan(tmp_path)
    execute = create_todoupdate_executor(runner)
    for index in range(3):
        result = asyncio.run(execute({"action": "add", "title": f"new {index}"}))
        assert result.is_error is False
    execute = create_todoupdate_executor(runner)
    fourth = asyncio.run(execute({"action": "add", "title": "blocked"}))
    assert fourth.is_error is False
    assert "最大调整次数" in fourth.output


def test_todoupdate_cannot_modify_done_step(tmp_path) -> None:
    runner = _runner_with_plan(tmp_path)
    execute = create_todoupdate_executor(runner)
    result = asyncio.run(execute({"action": "update", "step_id": 1, "title": "blocked"}))
    assert result.is_error is True
    assert runner._plan.steps[0].title == "done"
