from __future__ import annotations

import os

import pytest

from backend.core.s01_agent_loop import (
    PlanCheckpointStore,
    PlanExecuteRunner,
    PlanPhase,
    PlanState,
    PlanStore,
    TodoState,
    TodoStep,
    TodoStore,
    UserConfig,
    UserConfigStore,
)
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json, run_with_approval


def _state(
    plan_name: str,
    phase: PlanPhase = PlanPhase.EXECUTING,
    owner_id: str = "owner-1",
) -> PlanState:
    return PlanState(
        plan_name=plan_name,
        session_id="session-1",
        owner_id=owner_id,
        phase=phase,
        todo=TodoState(
            plan_name=plan_name,
            session_id="session-1",
            steps=[TodoStep(id=1, title="step", status="done")],
        ),
    )


def _runner(tmp_path, adapter: MockAdapter, owner_id: str = "runner-owner") -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
        owner_id=owner_id,
    )


def test_checkpoint_store_roundtrip_and_latest(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    first = store.save(_state("first-plan"))
    second = store.save(_state("second-plan", PlanPhase.COMPLETED))
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))

    loaded = store.load("session-1", "first-plan")
    latest = store.load_latest("session-1")

    assert loaded is not None
    assert loaded.todo is not None
    assert loaded.todo.steps[0].status == "done"
    assert latest is not None
    assert latest.plan_name == "second-plan"
    assert latest.phase == PlanPhase.COMPLETED
    assert store.list_checkpoints("session-1") == ["first-plan", "second-plan"]


def test_checkpoint_load_falls_back_to_backup_when_main_is_corrupt(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    state = _state("recoverable-plan", PlanPhase.EXECUTING)
    path = store.save(state)
    path.with_suffix(".bak").write_text(state.model_dump_json(indent=2), encoding="utf-8")
    path.write_text("{broken", encoding="utf-8")

    loaded = store.load("session-1", "recoverable-plan")

    assert loaded is not None
    assert loaded.plan_name == "recoverable-plan"
    assert loaded.phase == PlanPhase.EXECUTING


def test_checkpoint_load_falls_back_to_backup_when_main_is_missing(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    path = store.save(_state("backup-only-plan", PlanPhase.PAUSED))
    path.with_suffix(".bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()

    loaded = store.load("session-1", "backup-only-plan")
    latest = store.load_latest("session-1")

    assert loaded is not None
    assert loaded.phase == PlanPhase.PAUSED
    assert latest is not None
    assert latest.plan_name == "backup-only-plan"


def test_checkpoint_load_ignores_incomplete_tmp_file(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    path = store.save(_state("tmp-leftover-plan", PlanPhase.EXECUTING))
    path.with_suffix(".tmp").write_text("{incomplete", encoding="utf-8")

    loaded = store.load("session-1", "tmp-leftover-plan")

    assert loaded is not None
    assert loaded.plan_name == "tmp-leftover-plan"
    assert loaded.phase == PlanPhase.EXECUTING


def test_checkpoint_store_finds_incomplete_by_owner(tmp_path) -> None:
    store = PlanCheckpointStore(str(tmp_path))
    store.save(_state("active-plan", PlanPhase.EXECUTING, "owner-a"))
    store.save(_state("done-plan", PlanPhase.COMPLETED, "owner-a"))
    store.save(_state("other-plan", PlanPhase.PAUSED, "owner-b"))

    found = store.find_incomplete_by_owner("owner-a")

    assert [state.plan_name for state in found] == ["active-plan"]


def test_user_config_store_roundtrip_and_default(tmp_path) -> None:
    store = UserConfigStore(tmp_path / "user_configs")
    default = store.get("owner-a")
    store.save(UserConfig(owner_id="owner-a", auto_approve_tools=True))
    restored = store.get("owner-a")

    assert default.auto_approve_tools is False
    assert restored.auto_approve_tools is True
    assert restored.owner_id == "owner-a"


@pytest.mark.asyncio
async def test_runner_writes_completed_checkpoint(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=3), "done1", "done2", "done3"])
    runner = _runner(tmp_path, adapter)

    await run_with_approval(runner, "test")

    path = tmp_path / "plan_checkpoints" / f"test-session-{runner.plan_name}.json"
    state = PlanState.model_validate_json(path.read_text(encoding="utf-8"))
    assert state.owner_id == "runner-owner"
    assert state.phase == PlanPhase.COMPLETED
    assert state.current_step_id == 0
    assert state.todo is not None
    assert [step.status for step in state.todo.steps] == ["done", "done", "done"]
    assert (tmp_path / "plans" / f"{runner.plan_name}.md").exists()
    assert not (tmp_path / "todos" / f"test-session-plan-{runner.plan_name}.json").exists()


@pytest.mark.asyncio
async def test_runner_checkpoint_during_step_and_cancel(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=3), "done1", "done2"])
    runner = _runner(tmp_path, adapter)
    original_execute = runner._execute_step
    captured: list[PlanState] = []

    async def capture_second_step(step) -> None:
        if step.id == 2:
            store = PlanCheckpointStore(str(tmp_path / "plan_checkpoints"))
            state = store.load("test-session", runner.plan_name)
            assert state is not None
            captured.append(state)
            runner.cancel()
        await original_execute(step)

    runner._execute_step = capture_second_step
    await run_with_approval(runner, "test")

    assert captured[0].phase == PlanPhase.EXECUTING
    assert captured[0].current_step_id == 2
    assert captured[0].todo is not None
    assert [step.status for step in captured[0].todo.steps] == ["done", "running", "pending"]
    final = PlanCheckpointStore(str(tmp_path / "plan_checkpoints")).load(
        "test-session", runner.plan_name
    )
    assert final is not None
    assert final.phase == PlanPhase.CANCELLED
    assert final.interrupted_at is not None
