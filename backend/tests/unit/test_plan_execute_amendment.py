from __future__ import annotations

import pytest

from backend.core.s01_agent_loop import PlanExecuteRunner, PlanStore, TodoStore
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json, run_with_approval


def _runner(tmp_path, adapter: MockAdapter) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


@pytest.mark.asyncio
async def test_no_amendment_calls(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=2), "step1 done", "step2 done"])
    runner = _runner(tmp_path, adapter)
    await run_with_approval(runner, "test")
    prompts = [request.messages[0].content for request in adapter.requests]
    assert not any("计划修正审查者" in prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_summary_does_not_mention_amendment(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=1), "step done"])
    runner = _runner(tmp_path, adapter)
    await run_with_approval(runner, "test")
    assert "修正" not in runner.build_exit_summary().content
