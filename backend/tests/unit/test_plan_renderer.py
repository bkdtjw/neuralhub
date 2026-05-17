from __future__ import annotations

import asyncio
from typing import get_args

import pytest

from backend.common.types.agent import AgentEventType
from backend.core.s01_agent_loop import (
    ExecutionPlan,
    PlanExecuteRunner,
    PlanRenderer,
    PlanPhase,
    PlanStep,
    PlanStore,
    SilentPlanRenderer,
    TodoState,
    TodoStep,
    TodoStore,
)
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json, run_with_approval


def _plan(step_count: int = 2) -> ExecutionPlan:
    return ExecutionPlan(
        goal="test",
        approach=["a"],
        data_structures="",
        steps=[
            PlanStep(step_id=index, title=f"step{index}", description="d", tools_hint=[])
            for index in range(1, step_count + 1)
        ],
    )


def _todo(status: str = "completed") -> TodoState:
    return TodoState(
        plan_name="test-plan",
        session_id="s1",
        status=status,
        steps=[
            TodoStep(id=1, title="step1", status="done"),
            TodoStep(id=2, title="step2", status="pending"),
        ],
    )


def _runner(
    tmp_path, renderer: PlanRenderer, adapter: MockAdapter | None = None
) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter or MockAdapter(["侦察报告", plan_json(step_count=1), "done"]),
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        renderer=renderer,
        session_id="test-session",
    )


def test_silent_renderer_plan_created() -> None:
    asyncio.run(SilentPlanRenderer().on_plan_created(_plan(), "test-plan"))


def test_silent_renderer_recon_and_steps_updated() -> None:
    renderer = SilentPlanRenderer()
    asyncio.run(renderer.on_recon_start("goal"))
    asyncio.run(renderer.on_recon_done("report"))
    asyncio.run(
        renderer.on_steps_updated("test-plan", [{"id": 1}], [{"id": 1, "status": "pending"}])
    )


def test_silent_renderer_step_lifecycle() -> None:
    renderer = SilentPlanRenderer()
    asyncio.run(renderer.on_step_start(1, "step1", 2))
    asyncio.run(renderer.on_step_done(1, "step1", 1.2, "summary"))


def test_silent_renderer_step_failed() -> None:
    asyncio.run(SilentPlanRenderer().on_step_failed(2, "step2", "error msg"))


def test_silent_renderer_amendment() -> None:
    asyncio.run(SilentPlanRenderer().on_amendment("test-plan", 2, "reason", 2))


def test_silent_renderer_plan_completed() -> None:
    asyncio.run(SilentPlanRenderer().on_plan_completed("test-plan", _todo()))


def test_silent_renderer_plan_partial_failed() -> None:
    asyncio.run(
        SilentPlanRenderer().on_plan_partial_failed("test-plan", _todo("partial_failed"), 1, 1)
    )


def test_silent_renderer_plan_cancelled() -> None:
    asyncio.run(SilentPlanRenderer().on_plan_cancelled("test-plan", _todo("cancelled")))


@pytest.mark.asyncio
async def test_runner_with_silent_renderer_full_lifecycle(tmp_path) -> None:
    calls: list[tuple[str, object]] = []

    class SpyRenderer(SilentPlanRenderer):
        async def on_recon_start(self, goal: str) -> None:
            calls.append(("recon_start", goal))

        async def on_recon_done(self, report_preview: str) -> None:
            calls.append(("recon_done", report_preview))

        async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None:
            calls.append(("created", plan_name))

        async def on_plan_approved(self, plan_name: str) -> None:
            calls.append(("approved", plan_name))

        async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None:
            calls.append(("step_start", step_id))

        async def on_step_done(
            self,
            step_id: int,
            title: str,
            duration_s: float,
            output_summary: str,
        ) -> None:
            calls.append(("step_done", step_id))

        async def on_plan_completed(self, plan_name: str, todo_state: TodoState) -> None:
            calls.append(("completed", plan_name))

    runner = _runner(tmp_path, SpyRenderer())
    await run_with_approval(runner, "test")

    assert ("recon_start", "test") in calls
    assert any(call[0] == "recon_done" for call in calls)
    assert ("created", runner.plan_name) in calls
    assert ("approved", runner.plan_name) in calls
    assert ("step_start", 1) in calls
    assert ("step_done", 1) in calls
    assert ("completed", runner.plan_name) in calls


@pytest.mark.asyncio
async def test_runner_renderer_failure_does_not_block(tmp_path) -> None:
    class BrokenRenderer(SilentPlanRenderer):
        async def on_step_done(self, *args: object) -> None:
            raise RuntimeError("renderer crash")

    runner = _runner(tmp_path, BrokenRenderer())
    await run_with_approval(runner, "test")
    assert runner.status == PlanPhase.COMPLETED


@pytest.mark.asyncio
async def test_cancel_triggers_renderer(tmp_path) -> None:
    calls: list[str] = []

    class SpyRenderer(SilentPlanRenderer):
        async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None:
            calls.append("cancelled")

    runner = _runner(
        tmp_path,
        SpyRenderer(),
        MockAdapter(["侦察报告", plan_json(step_count=2), "step1 done", "step2 done"]),
    )
    original_execute = runner._execute_step

    async def cancel_after_first(step: TodoStep) -> None:
        await original_execute(step)
        if step.id == 1:
            runner.cancel()

    runner._execute_step = cancel_after_first
    await run_with_approval(runner, "test")
    assert "cancelled" in calls


def test_silent_renderer_satisfies_protocol() -> None:
    assert isinstance(SilentPlanRenderer(), PlanRenderer)


def test_agent_event_type_includes_plan_events() -> None:
    args = get_args(AgentEventType)
    assert "plan_created" in args
    assert "plan_step_start" in args
    assert "plan_completed" in args
    assert "plan_cancelled" in args
