from __future__ import annotations

import pytest

from backend.core.s01_agent_loop import PlanExecuteRunner, PlanStore, TodoStore
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import (
    VALID_PLAN_JSON,
    MockAdapter,
    run_with_approval,
)


def _runner(tmp_path: object, adapter: MockAdapter) -> PlanExecuteRunner:
    root = tmp_path
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(root / "plans")),
        todo_store=TodoStore(str(root / "todos")),
        session_id="test-session",
    )


@pytest.mark.asyncio
async def test_runner_uses_recon_plan_without_planning_request(tmp_path) -> None:
    adapter = MockAdapter([VALID_PLAN_JSON, "done"])
    runner = _runner(tmp_path, adapter)
    result = await run_with_approval(runner, "test")
    assert result.role == "assistant"
    planning_requests = [
        request
        for request in adapter.requests
        if "Plan & Execute 规划者" in request.messages[0].content
    ]
    assert planning_requests == []
    assert runner._plan is not None and runner._plan.goal == "LLM生成的目标"


@pytest.mark.asyncio
async def test_runner_degrades_bad_recon_to_single_step_plan(tmp_path) -> None:
    runner = _runner(tmp_path, MockAdapter(["垃圾", "done"]))
    await run_with_approval(runner, "test")
    assert runner._todo_state is not None
    assert [step.title for step in runner._todo_state.steps] == ["执行用户任务"]


@pytest.mark.asyncio
async def test_runner_plan_file_from_recon_plan(tmp_path) -> None:
    runner = _runner(tmp_path, MockAdapter([VALID_PLAN_JSON]))
    await run_with_approval(runner, "test")
    plan_path = tmp_path / "plans" / f"{runner.plan_name}.md"
    detail_path = tmp_path / "plans" / f"test-session-{runner.plan_name}.md"
    assert "LLM生成的目标" in plan_path.read_text(encoding="utf-8")
    assert "## 分步执行计划" in detail_path.read_text(encoding="utf-8")
