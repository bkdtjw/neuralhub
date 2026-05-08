from __future__ import annotations

import asyncio

from backend.core.s01_agent_loop import (
    PlanControlStore,
    PlanExecuteRunner,
    PlanStatus,
    PlanStore,
    TodoStore,
)
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json


def _runner(tmp_path, adapter: MockAdapter) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


def test_pause_waits_before_next_step_and_applies_instruction(tmp_path) -> None:
    async def scenario() -> PlanExecuteRunner:
        adapter = MockAdapter(["侦察报告", plan_json(step_count=2), "step1", "step2"])
        runner = _runner(tmp_path, adapter)
        original_execute = runner._execute_step

        async def pause_after_first(step) -> None:
            await original_execute(step)
            if step.id == 1:
                runner.pause()

        runner._execute_step = pause_after_first
        task = asyncio.create_task(runner.run("test"))
        for _ in range(100):
            if runner.status == PlanStatus.PAUSED:
                break
            await asyncio.sleep(0.01)
        assert runner.status == PlanStatus.PAUSED
        assert runner._todo_state.steps[1].status == "pending"
        runner.resume("后续步骤增加验证")
        await task
        prompt = "\n".join(message.content for message in adapter.requests[3].messages)
        assert "后续步骤增加验证" in prompt
        return runner

    runner = asyncio.run(scenario())
    assert runner.status == PlanStatus.COMPLETED


def test_shared_pause_signal_waits_before_next_step(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PLAN_CONTROL_DIR", str(tmp_path / "controls"))

    async def scenario() -> PlanExecuteRunner:
        adapter = MockAdapter(["侦察报告", plan_json(step_count=2), "step1", "step2"])
        runner = _runner(tmp_path, adapter)
        original_execute = runner._execute_step

        async def pause_after_first(step) -> None:
            await original_execute(step)
            if step.id == 1:
                PlanControlStore().request_pause("test-session")

        runner._execute_step = pause_after_first
        task = asyncio.create_task(runner.run("test"))
        for _ in range(150):
            if runner.status == PlanStatus.PAUSED:
                break
            await asyncio.sleep(0.02)
        assert runner.status == PlanStatus.PAUSED
        PlanControlStore().request_resume("test-session", "共享补充")
        await task
        prompt = "\n".join(message.content for message in adapter.requests[3].messages)
        assert "共享补充" in prompt
        return runner

    runner = asyncio.run(scenario())
    assert runner.status == PlanStatus.COMPLETED
