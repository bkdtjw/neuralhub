from __future__ import annotations

import asyncio

import pytest

from backend.core.s01_agent_loop import (
    ExecutionPlan,
    PlanCheckpointStore,
    PlanExecuteRunner,
    PlanPhase,
    PlanState,
    PlanStep,
    PlanStore,
    TodoState,
    TodoStep,
    TodoStore,
)
from backend.core.s01_agent_loop.plan_renderer import SilentPlanRenderer
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json


class SpyRenderer(SilentPlanRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None:
        self.events.append("created")

    async def on_plan_approved(self, plan_name: str) -> None:
        self.events.append("approved")

    async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None:
        self.events.append(f"step_start:{step_id}")

    async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None:
        self.events.append("cancelled")


def _runner(tmp_path, adapter: MockAdapter, renderer: SpyRenderer) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        renderer=renderer,
        session_id="test-session",
    )


async def _wait_phase(runner: PlanExecuteRunner, phase: PlanPhase) -> None:
    for _ in range(100):
        if runner.phase == phase:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"runner did not enter {phase.value}")


async def _wait_event(renderer: SpyRenderer, event: str) -> None:
    for _ in range(100):
        if event in renderer.events:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"renderer did not emit {event}")


@pytest.mark.asyncio
async def test_runner_waits_for_approval_before_executing_steps(tmp_path) -> None:
    renderer = SpyRenderer()
    runner = _runner(tmp_path, MockAdapter(["侦察报告", plan_json(step_count=1), "done"]), renderer)

    task = asyncio.create_task(runner.run("test"))
    await _wait_phase(runner, PlanPhase.AWAITING_APPROVAL)
    await _wait_event(renderer, "created")

    assert renderer.events == ["created"]
    assert runner._todo_state is not None
    assert [step.status for step in runner._todo_state.steps] == ["pending"]

    runner.approve()
    await task

    assert "approved" in renderer.events
    assert "step_start:1" in renderer.events
    assert runner.phase == PlanPhase.COMPLETED


@pytest.mark.asyncio
async def test_runner_reject_cancels_without_executing_steps(tmp_path) -> None:
    renderer = SpyRenderer()
    runner = _runner(tmp_path, MockAdapter(["侦察报告", plan_json(step_count=1), "done"]), renderer)

    task = asyncio.create_task(runner.run("test"))
    await _wait_phase(runner, PlanPhase.AWAITING_APPROVAL)
    await _wait_event(renderer, "created")
    runner.reject("no")
    await task

    assert renderer.events == ["created", "cancelled"]
    assert runner._todo_state is not None
    assert [step.status for step in runner._todo_state.steps] == ["skipped"]
    assert runner.phase == PlanPhase.CANCELLED
    assert runner._state.error_message == "no"


@pytest.mark.asyncio
async def test_runner_approval_timeout_cancels_plan(tmp_path) -> None:
    renderer = SpyRenderer()
    runner = _runner(tmp_path, MockAdapter(["侦察报告", plan_json(step_count=1), "done"]), renderer)
    runner._approval_timeout_seconds = 0.05

    await runner.run("test")

    assert renderer.events == ["created", "cancelled"]
    assert runner.phase == PlanPhase.CANCELLED
    assert "超时" in runner._state.error_message


@pytest.mark.asyncio
async def test_resume_awaiting_approval_waits_again(tmp_path) -> None:
    plan = ExecutionPlan(
        goal="resume",
        steps=[PlanStep(step_id=1, title="step1", description="do it")],
    )
    checkpoint_store = PlanCheckpointStore(str(tmp_path / "plan_checkpoints"))
    runner_state = PlanState(
        plan_name="resume-plan",
        session_id="test-session",
        phase=PlanPhase.AWAITING_APPROVAL,
        plan=plan,
        todo=TodoState(
            plan_name="resume-plan",
            session_id="test-session",
            steps=[TodoStep(id=1, title="step1", status="pending")],
        ),
    )
    checkpoint_store.save(runner_state)
    assert runner_state.phase == PlanPhase.AWAITING_APPROVAL
    renderer = SpyRenderer()
    runner = PlanExecuteRunner.resume_from_checkpoint(
        checkpoint_store,
        "test-session",
        MockAdapter(["done"]),
        ToolRegistry(),
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
        renderer,
    )
    assert runner is not None

    task = asyncio.create_task(runner.resume_run())
    await _wait_event(renderer, "created")
    assert renderer.events == ["created"]

    runner.approve()
    await task

    assert renderer.events[:2] == ["created", "approved"]
    assert runner.phase == PlanPhase.COMPLETED
