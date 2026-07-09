from __future__ import annotations

import pytest

from backend.common.types import LLMRequest, LLMResponse
from backend.core.s01_agent_loop import PlanCheckpointStore, PlanExecuteRunner, PlanStore, TodoStore
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import (
    MockAdapter,
    plan_json,
    resume_with_approval,
    run_with_approval,
)


class SimulatedCrash(BaseException):
    pass


def _runner(tmp_path, adapter: MockAdapter) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


@pytest.mark.asyncio
async def test_step_result_resume_skips_completed_steps(tmp_path) -> None:
    class CrashAtStep3Adapter(MockAdapter):
        async def complete(self, request: LLMRequest) -> LLMResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return LLMResponse(content=plan_json(step_count=3))
            if len(self.requests) == 2:
                return LLMResponse(content="done1")
            if len(self.requests) == 3:
                return LLMResponse(content="done2")
            raise SimulatedCrash("crash during step 3")

    crashed = _runner(tmp_path, CrashAtStep3Adapter())
    with pytest.raises(SimulatedCrash):
        await run_with_approval(crashed, "test")

    stored = crashed._step_result_store.list("test-session", crashed._plan_name)
    assert [result.step_id for result in stored[:2]] == [1, 2]

    resumed = PlanExecuteRunner.resume_from_checkpoint(
        PlanCheckpointStore(str(tmp_path / "plan_checkpoints")),
        "test-session",
        MockAdapter(["done3"]),
        ToolRegistry(),
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
    )
    assert resumed is not None
    await resume_with_approval(resumed)

    assert [step.status for step in resumed._todo_state.steps] == ["done", "done", "done"]
    assert len(resumed._adapter.requests) == 1
    assert resumed._adapter.requests[0].messages[-1].content.startswith("请执行计划第 3/3")
