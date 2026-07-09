from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from backend.core.s01_agent_loop.step_result import StepResult, StepResultStore, StepStatus


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯文件系统单测，跳过 PostgresContainer 避免拖慢。
    yield


def _step(step_id: int, task: str) -> StepResult:
    return StepResult(
        step_id=step_id,
        request_id=f"request-{step_id}",
        status=StepStatus.DONE,
        task=task,
        result_summary=task,
    )


def test_new_plan_does_not_see_previous_plan_results(tmp_path) -> None:
    # 同一 session 下先跑 plan_A，再跑 plan_B：plan_B 不应读到 plan_A 的步骤结果。
    store = StepResultStore(tmp_path / "steps")
    session_id = "session-shared"

    store.write(session_id, "plan_A", _step(1, "plan_A step 1"))
    store.write(session_id, "plan_A", _step(2, "plan_A step 2"))

    assert store.list(session_id, "plan_B") == []
    assert store.read(session_id, "plan_B", 1) is None


def test_same_plan_read_write_roundtrip(tmp_path) -> None:
    store = StepResultStore(tmp_path / "steps")
    session_id = "session-shared"

    written = _step(1, "plan_A step 1")
    store.write(session_id, "plan_A", written)

    assert store.read(session_id, "plan_A", 1) == written
    assert [result.step_id for result in store.list(session_id, "plan_A")] == [1]


def test_two_plans_in_same_session_are_isolated(tmp_path) -> None:
    # plan_A 与 plan_B 各写各的，互不串扰。
    store = StepResultStore(tmp_path / "steps")
    session_id = "session-shared"

    store.write(session_id, "plan_A", _step(1, "plan_A step 1"))
    store.write(session_id, "plan_B", _step(1, "plan_B step 1"))

    plan_a = store.read(session_id, "plan_A", 1)
    plan_b = store.read(session_id, "plan_B", 1)
    assert plan_a is not None and plan_a.task == "plan_A step 1"
    assert plan_b is not None and plan_b.task == "plan_B step 1"
    assert [result.task for result in store.list(session_id, "plan_A")] == ["plan_A step 1"]
    assert [result.task for result in store.list(session_id, "plan_B")] == ["plan_B step 1"]
