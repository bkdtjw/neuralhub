from __future__ import annotations

import asyncio
import re

import pytest

from backend.core.s01_agent_loop import (
    ExecutionPlan,
    PlanExecuteRunner,
    PlanParseError,
    PlanStatus,
    PlanStep,
    PlanStore,
    TodoStore,
    generate_plan_name,
)
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import VALID_PLAN_JSON, MockAdapter


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        goal="test",
        approach=["step1"],
        data_structures="",
        steps=[PlanStep(step_id=1, title="step1", description="d1", tools_hint=[])],
        version=1,
    )


def _runner(tmp_path: object, adapter: MockAdapter | None = None) -> PlanExecuteRunner:
    root = tmp_path
    return PlanExecuteRunner(
        adapter=adapter or MockAdapter(),
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(root / "plans")),
        todo_store=TodoStore(str(root / "todos")),
        session_id="test-session",
    )


def test_execution_plan_roundtrip() -> None:
    plan = ExecutionPlan(
        goal="refactor s07",
        approach=["read code", "analyze deps", "split files"],
        data_structures="TaskExecutor splits into three classes",
        steps=[
            PlanStep(
                step_id=1,
                title="read code",
                description="read all files",
                tools_hint=["Read", "Bash"],
            )
        ],
        version=1,
    )
    restored = ExecutionPlan.model_validate_json(plan.model_dump_json())
    assert restored.goal == plan.goal
    assert len(restored.steps) == 1
    assert restored.version == 1


def test_plan_store_save_and_read(tmp_path) -> None:
    store = PlanStore(base_dir=str(tmp_path / "plans"))
    path = store.save_plan("test-plan-alpha", _plan())
    assert path.exists()
    assert path.suffix == ".md"
    assert "## Goal" in path.read_text(encoding="utf-8")
    assert "test-plan-alpha" in store.list_plans()
    restored = store.read_plan("test-plan-alpha")
    assert restored.goal == "test"
    assert restored.version == 1


def test_plan_store_update(tmp_path) -> None:
    store = PlanStore(base_dir=str(tmp_path / "plans"))
    plan = _plan()
    store.save_plan("test-amend", plan)
    plan_v2 = plan.model_copy(update={"version": 2, "approach": ["step1", "b-amended"]})
    store.update_plan("test-amend", plan_v2)
    content = (tmp_path / "plans" / "test-amend.md").read_text(encoding="utf-8")
    assert "## Amendment Log" in content
    assert "Version 2" in content or "v2" in content.lower()
    restored = store.read_plan("test-amend")
    assert restored.version == 2
    assert restored.approach == ["step1", "b-amended"]


def test_todo_store_create_and_update(tmp_path) -> None:
    store = TodoStore(base_dir=str(tmp_path / "todos"))
    steps = [PlanStep(step_id=1, title="step1", description="d1", tools_hint=[])]
    state = store.create("session-abc", "test-plan", steps)
    assert state.status == "pending"
    assert len(state.steps) == 1
    assert state.steps[0].status == "pending"
    state.status = "executing"
    store.update("session-abc", "test-plan", state)
    assert len(store.list_active()) == 1
    state.steps[0].status = "done"
    state.steps[0].duration_s = 3.5
    state.status = "completed"
    store.update("session-abc", "test-plan", state)
    restored = store.read("session-abc", "test-plan")
    assert restored is not None
    assert restored.steps[0].status == "done"
    assert restored.status == "completed"


def test_runner_full_lifecycle(tmp_path) -> None:
    runner = _runner(tmp_path)
    assert runner.status == PlanStatus.IDLE
    result = asyncio.run(runner.run("refactor s07"))
    assert result.role == "assistant"
    assert runner.status in (PlanStatus.COMPLETED, PlanStatus.CANCELLED)
    assert runner.plan_name
    assert (tmp_path / "plans" / f"{runner.plan_name}.md").exists()
    assert runner._todo_state is not None
    assert all(step.status == "done" for step in runner._todo_state.steps)


def test_runner_cancel(tmp_path) -> None:
    runner = _runner(tmp_path)
    original_execute = runner._execute_step

    async def cancel_on_second(step) -> None:
        await original_execute(step)
        if step.id == 2:
            runner.cancel()

    runner._execute_step = cancel_on_second
    asyncio.run(runner.run("cancel midway"))
    assert runner.status == PlanStatus.CANCELLED
    assert runner._todo_state is not None
    assert runner._todo_state.cancelled_at is not None
    assert [step.status for step in runner._todo_state.steps] == ["done", "done", "skipped"]


def test_exit_summary_content(tmp_path) -> None:
    runner = _runner(tmp_path)
    asyncio.run(runner.run("summarize"))
    summary = runner.build_exit_summary()
    assert summary.role == "assistant"
    assert runner.plan_name in summary.content
    assert "✅" in summary.content or "⬜" in summary.content
    assert "plans/" in summary.content
    assert "todos/" in summary.content


def test_plan_name_format() -> None:
    for _ in range(20):
        name = generate_plan_name()
        assert re.match(r"^[a-z]+-[a-z]+-[a-z]+$", name)
        assert len(name) < 60


def test_runner_planning_retry_on_parse_failure(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", "不是JSON", VALID_PLAN_JSON])
    runner = _runner(tmp_path, adapter)
    result = asyncio.run(runner.run("test"))
    assert result.role == "assistant"
    planning_requests = [
        request
        for request in adapter.requests
        if "Plan & Execute 规划者" in request.messages[0].content
    ]
    assert len(planning_requests) == 2
    assert runner.plan_name


def test_runner_planning_fail_after_retry(tmp_path) -> None:
    runner = _runner(tmp_path, MockAdapter(["侦察报告", "垃圾", "仍然垃圾"]))
    with pytest.raises(PlanParseError):
        asyncio.run(runner.run("test"))


def test_runner_plan_file_from_llm(tmp_path) -> None:
    runner = _runner(tmp_path, MockAdapter(["侦察报告", VALID_PLAN_JSON]))
    asyncio.run(runner.run("test"))
    plan_content = (tmp_path / "plans" / f"{runner.plan_name}.md").read_text(encoding="utf-8")
    assert "LLM生成的目标" in plan_content
