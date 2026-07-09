from __future__ import annotations

import pytest

from backend.core.s01_agent_loop.step_result import StepResult, StepResultStore, StepStatus


def test_step_result_store_roundtrip(tmp_path) -> None:
    store = StepResultStore(tmp_path / "steps")
    first = StepResult(
        step_id=2,
        request_id="request-2",
        status=StepStatus.DONE,
        task="second",
        result_summary="done",
        key_data={"count": 2},
    )
    second = StepResult(
        step_id=1,
        request_id="request-1",
        status=StepStatus.FAILED,
        task="first",
        result_summary="failed",
    )

    first_path = store.write("session-1", "plan-a", first)
    store.write("session-1", "plan-a", second)

    assert first_path.name == "step_2.json"
    assert store.read("session-1", "plan-a", 2) == first
    assert [result.step_id for result in store.list("session-1", "plan-a")] == [1, 2]


def test_step_result_store_rejects_path_injection(tmp_path) -> None:
    store = StepResultStore(tmp_path / "steps")

    with pytest.raises(ValueError):
        store.read("../bad", "plan-a", 1)
