from __future__ import annotations

import asyncio
import json

import pytest

from backend.common.types import AgentConfig, LLMRequest, LLMResponse, Message, ToolCall
from backend.core.s01_agent_loop import (
    AgentLoop,
    PlanExecuteRunner,
    PlanStore,
    TodoState,
    TodoStore,
)
from backend.core.s01_agent_loop.plan_step_checkpoint import _restore_step_messages
from backend.core.s02_tools import ToolRegistry
from backend.storage.session_store import SessionStore
from backend.tests.unit.plan_execute_test_support import MockAdapter, plan_json, run_with_approval


class SimulatedCrash(BaseException):
    pass


def _runner(tmp_path, adapter: MockAdapter, session_id: str = "test-session") -> PlanExecuteRunner:
    return PlanExecuteRunner(
        adapter=adapter,
        tool_registry=ToolRegistry(),
        plan_store=PlanStore(str(tmp_path / "plans")),
        todo_store=TodoStore(str(tmp_path / "todos")),
        session_id=session_id,
    )


@pytest.mark.asyncio
async def test_plan_steps_checkpoint_messages_and_todo_json(tmp_path) -> None:
    adapter = MockAdapter(["侦察报告", plan_json(step_count=3), "done1", "done2", "done3"])
    runner = _runner(tmp_path, adapter)

    await run_with_approval(runner, "test")

    assert runner._todo_state is not None
    state = runner._checkpoint_store.load("test-session", runner.plan_name)
    assert state is not None and state.todo is not None
    store = SessionStore()
    for step in runner._todo_state.steps:
        expected = f"test-session-plan-{runner.plan_name}-step-{step.id}"
        assert step.checkpoint_session_id == expected
        assert state.todo.steps[step.id - 1].checkpoint_session_id == expected
        messages = await store.get_messages(expected)
        assert [message.role for message in messages[:3]] == ["system", "user", "assistant"]


@pytest.mark.asyncio
async def test_plan_step_checkpoint_session_id_is_shortened_for_long_owner(tmp_path) -> None:
    long_session_id = "feishu-oc_" + ("9" * 48)
    adapter = MockAdapter(["侦察报告", plan_json(step_count=1), "done1"])
    runner = _runner(tmp_path, adapter, session_id=long_session_id)

    await run_with_approval(runner, "test")

    assert runner._todo_state is not None
    step = runner._todo_state.steps[0]
    assert len(step.checkpoint_session_id) <= 64
    assert step.checkpoint_session_id.startswith("plan-step-")
    state = runner._checkpoint_store.load(long_session_id, runner.plan_name)
    assert state is not None and state.todo is not None
    assert state.todo.steps[0].checkpoint_session_id == step.checkpoint_session_id
    messages = await SessionStore().get_messages(step.checkpoint_session_id)
    assert [message.role for message in messages[:3]] == ["system", "user", "assistant"]


def test_todo_state_reads_old_json_without_checkpoint_session_id() -> None:
    payload = {"plan_name": "old-plan", "session_id": "sid", "steps": [{"id": 1, "title": "step"}]}
    state = TodoState.model_validate_json(json.dumps(payload))

    assert state.steps[0].checkpoint_session_id == ""


@pytest.mark.asyncio
async def test_plan_step_checkpoint_survives_simulated_crash(tmp_path) -> None:
    class CrashAdapter(MockAdapter):
        async def complete(self, request: LLMRequest) -> LLMResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                return LLMResponse(content="侦察报告")
            if len(self.requests) == 2:
                return LLMResponse(content=plan_json(step_count=3))
            if len(self.requests) == 3:
                return LLMResponse(content="done1")
            raise SimulatedCrash("crash during step 2")

    runner = _runner(tmp_path, CrashAdapter())
    with pytest.raises(SimulatedCrash):
        await run_with_approval(runner, "test")

    assert runner._todo_state is not None
    store = SessionStore()
    step2_id = f"test-session-plan-{runner.plan_name}-step-2"
    step3_id = f"test-session-plan-{runner.plan_name}-step-3"
    assert [message.role for message in await store.get_messages(step2_id)] == ["system", "user"]
    assert await store.get_messages(step3_id) == []


@pytest.mark.asyncio
async def test_execute_step_restores_existing_checkpoint_messages(tmp_path, monkeypatch) -> None:
    class RestoreAdapter(MockAdapter):
        def __init__(self) -> None:
            super().__init__([])
            self.request_messages: list[Message] = []

        async def complete(self, request: LLMRequest) -> LLMResponse:
            self.requests.append(request)
            self.request_messages = request.messages
            return LLMResponse(content="step2 resumed")

    events: list[tuple[str, dict[str, object]]] = []

    class FakeLogger:
        def info(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    import backend.core.s01_agent_loop.plan_step_checkpoint as checkpoint_module

    monkeypatch.setattr(checkpoint_module, "logger", FakeLogger())
    crash_adapter = MockAdapter(["侦察报告", plan_json(step_count=3), "done1"])
    runner = _runner(tmp_path, crash_adapter)
    await run_with_approval(runner, "test")
    runner._adapter = RestoreAdapter()
    step2 = runner._todo_state.steps[1]
    store = SessionStore()
    await store.add_messages(step2.checkpoint_session_id, [Message(role="assistant", content="partial")])

    await runner._execute_step(step2)

    assert [message.role for message in runner._adapter.request_messages[:3]] == [
        "system",
        "user",
        "assistant",
    ]
    assert events and events[0][0] == "plan_step_checkpoint_restored"


def test_restore_step_messages_sanitizes_orphan_tool_calls() -> None:
    loop = AgentLoop(
        config=AgentConfig(model="", system_prompt="system", session_id="restore-test"),
        adapter=MockAdapter(),
        tool_registry=ToolRegistry(),
    )
    restored = _restore_step_messages(
        loop,
        [
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="tool-1", name="Read", arguments={"path": "x.py"})],
            )
        ],
    )

    assert [message.role for message in restored] == ["system", "assistant", "tool"]
    assert restored[2].tool_results is not None
    assert restored[2].tool_results[0].tool_call_id == "tool-1"
    assert restored[2].tool_results[0].is_error is True
