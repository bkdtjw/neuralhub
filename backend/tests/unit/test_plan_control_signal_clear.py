from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from backend.common.types import Message
from backend.core.s01_agent_loop.plan_control import PlanControlState
from backend.core.s01_agent_loop.plan_control_store import PlanControlStore
from backend.core.s01_agent_loop.plan_execute_runner_state import PlanExecuteRunnerStateMixin
from backend.core.s01_agent_loop.plan_execute_runner_steps import PlanExecuteRunnerStepsMixin
from backend.core.s01_agent_loop.plan_models import PlanPhase, PlanState
from backend.core.s01_agent_loop.plan_resume import PlanResumeMixin


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


@pytest.fixture
def control_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "plan_controls"
    target.mkdir()
    monkeypatch.setenv("PLAN_CONTROL_DIR", str(target))
    return target


def _signal_files(control_dir: Path) -> list[Path]:
    return list(control_dir.glob("*.json"))


class _StepsStub(PlanExecuteRunnerStepsMixin):
    # 只保留 _apply_control_signal 依赖的最小状态。
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._control = PlanControlState()
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class _StateStub(PlanExecuteRunnerStateMixin):
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._owner_id = "owner"
        self._state = PlanState(plan_name="", session_id=session_id, owner_id="owner")
        self._cancel_requested = False
        self._plan_path = None
        self._todo_path = None


class _ResumeStub(PlanResumeMixin):
    # mock 掉真正执行步骤，只验证 resume 开始时的信号清理。
    def __init__(self, session_id: str, phase: PlanPhase) -> None:
        self._session_id = session_id
        self._state = PlanState(plan_name="p", session_id=session_id, owner_id="owner")
        self._state.phase = phase
        self.executed = False

    async def _execute_existing_plan(self) -> None:
        self.executed = True

    async def _finish_run(self) -> Message:
        return Message(role="assistant", content="finished")

    def _persist_state(self, **_kwargs: object) -> None:
        pass


def test_apply_control_signal_stop_applies_and_clears(control_dir: Path) -> None:
    PlanControlStore().request_stop("s1")
    stub = _StepsStub("s1")
    stub._apply_control_signal()
    assert stub.cancel_calls == 1
    assert PlanControlStore().read("s1").action == ""
    assert _signal_files(control_dir) == []


def test_apply_control_signal_pause_applies_and_clears(control_dir: Path) -> None:
    PlanControlStore().request_pause("s1")
    stub = _StepsStub("s1")
    stub._apply_control_signal()
    assert stub._control.pause_requested is True
    assert _signal_files(control_dir) == []  # 转内存态后文件被清除


def test_apply_control_signal_resume_applies_and_clears(control_dir: Path) -> None:
    PlanControlStore().request_resume("s1", "keep going")
    stub = _StepsStub("s1")
    stub._control.request_pause()
    stub._apply_control_signal()
    assert stub._control.pause_requested is False
    assert stub._control.consume_instruction() == "keep going"
    assert _signal_files(control_dir) == []


def test_apply_control_signal_empty_is_noop(control_dir: Path) -> None:
    stub = _StepsStub("s1")
    stub._apply_control_signal()
    assert stub.cancel_calls == 0
    assert stub._control.pause_requested is False
    assert _signal_files(control_dir) == []


def test_reset_state_clears_leftover_signal(control_dir: Path) -> None:
    PlanControlStore().request_stop("run-1")
    assert _signal_files(control_dir) != []
    stub = _StateStub("run-1")
    stub._reset_state("plan-x")
    assert stub._state.plan_name == "plan-x"
    assert _signal_files(control_dir) == []


@pytest.mark.asyncio
async def test_resume_run_clears_leftover_signal(control_dir: Path) -> None:
    PlanControlStore().request_stop("resume-1")
    assert _signal_files(control_dir) != []
    stub = _ResumeStub("resume-1", PlanPhase.EXECUTING)
    result = await stub.resume_run()
    # 遗留 stop 已被清除：执行照常进入，未被误判为取消。
    assert stub.executed is True
    assert result.content == "finished"
    assert _signal_files(control_dir) == []
