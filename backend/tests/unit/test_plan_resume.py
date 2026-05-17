from __future__ import annotations

import pytest

from backend.common.types import LLMRequest, LLMResponse, ToolCall, ToolDefinition, ToolParameterSchema, ToolResult
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
from backend.core.s02_tools import ToolRegistry
from backend.storage.session_store import SessionStore
from backend.tests.unit.plan_execute_test_support import (
    MockAdapter,
    plan_json,
    resume_with_approval,
    run_with_approval,
)


class SimulatedCrash(BaseException):
    pass


def _runner(tmp_path, adapter: MockAdapter, registry: ToolRegistry | None = None) -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=registry or ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id="test-session",
    )


def _registry_with_reader() -> ToolRegistry:
    async def read_path(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="关键发现第一行")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read_path",
            description="read",
            category="file-ops",
            parameters=ToolParameterSchema(),
        ),
        read_path,
    )
    return registry


def _tool_call(path: str) -> LLMResponse:
    return LLMResponse(content="", tool_calls=[ToolCall(id=f"tc-{path}", name="read_path", arguments={"path": path})])


def test_reset_interrupted_steps_only_resets_running(tmp_path) -> None:
    state = PlanState(
        plan_name="resume-plan",
        session_id="test-session",
        phase=PlanPhase.EXECUTING,
        todo=TodoState(
            plan_name="resume-plan",
            session_id="test-session",
            steps=[
                TodoStep(id=1, title="done", status="done"),
                TodoStep(id=2, title="running", status="running"),
                TodoStep(id=3, title="failed", status="failed"),
                TodoStep(id=4, title="skipped", status="skipped"),
            ],
        ),
    )
    checkpoint_store = PlanCheckpointStore(str(tmp_path / "plan_checkpoints"))
    checkpoint_store.save(state)

    runner = PlanExecuteRunner.resume_from_checkpoint(
        checkpoint_store,
        "test-session",
        MockAdapter(),
        ToolRegistry(),
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
    )

    assert runner is not None
    assert [step.status for step in runner._todo_state.steps] == ["done", "pending", "failed", "skipped"]


@pytest.mark.asyncio
async def test_resume_run_skips_done_steps_and_restores_step_checkpoint(tmp_path) -> None:
    class CrashAtStep3Adapter(MockAdapter):
        async def complete(self, request: LLMRequest) -> LLMResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return LLMResponse(content="侦察报告")
            if len(self.requests) == 2:
                return LLMResponse(content=plan_json(step_count=5))
            if len(self.requests) == 3:
                return _tool_call("a.py")
            if len(self.requests) == 4:
                return LLMResponse(content="done1")
            if len(self.requests) == 5:
                return _tool_call("b.py")
            if len(self.requests) == 6:
                return LLMResponse(content="done2")
            raise SimulatedCrash("crash during step 3")

    registry = _registry_with_reader()
    crashed = _runner(tmp_path, CrashAtStep3Adapter(), registry)
    with pytest.raises(SimulatedCrash):
        await run_with_approval(crashed, "test")

    step3_session = f"test-session-plan-{crashed.plan_name}-step-3"
    before_messages = await SessionStore().get_messages(step3_session)
    assert [message.role for message in before_messages] == ["system", "user"]

    resume_adapter = MockAdapter(["resumed3", "done4", "done5"])
    resumed = PlanExecuteRunner.resume_from_checkpoint(
        PlanCheckpointStore(str(tmp_path / "plan_checkpoints")),
        "test-session",
        resume_adapter,
        registry,
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
    )
    assert resumed is not None
    await resume_with_approval(resumed)

    assert [step.status for step in resumed._todo_state.steps] == ["done", "done", "done", "done", "done"]
    assert len(resume_adapter.requests) == 3
    first_resume_prompt = "\n".join(message.content for message in resume_adapter.requests[0].messages)
    assert "a.py" in first_resume_prompt
    assert "b.py" in first_resume_prompt
    assert [message.role for message in resume_adapter.requests[0].messages[:3]] == ["system", "user", "user"]
    after_messages = await SessionStore().get_messages(step3_session)
    assert len(after_messages) > len(before_messages)


@pytest.mark.asyncio
async def test_resume_recon_phase_replans_without_error(tmp_path) -> None:
    state = PlanState(plan_name="recon-plan", session_id="test-session", phase=PlanPhase.RECON)
    checkpoint_store = PlanCheckpointStore(str(tmp_path / "plan_checkpoints"))
    checkpoint_store.save(state)
    runner = PlanExecuteRunner.resume_from_checkpoint(
        checkpoint_store,
        "test-session",
        MockAdapter(["侦察报告", plan_json(step_count=1), "done"]),
        ToolRegistry(),
        PlanStore(str(tmp_path / "plans")),
        TodoStore(str(tmp_path / "todos")),
    )

    assert runner is not None
    await resume_with_approval(runner)
    assert runner.phase == PlanPhase.COMPLETED
