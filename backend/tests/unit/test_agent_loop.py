from __future__ import annotations

from collections.abc import AsyncIterator
import json

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.logging import setup_logging
from backend.common.types import AgentConfig, LLMRequest, LLMResponse, StreamChunk, ToolCall, ToolDefinition, ToolParameterSchema, ToolResult
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s02_tools.registry import ToolRegistry


class MockAdapter(LLMAdapter):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []
        self._index = 0

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._index >= len(self.responses):
            return LLMResponse(content="")
        response = self.responses[self._index]
        self._index += 1
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, category="shell", parameters=ToolParameterSchema())


def test_agent_loop_metadata_defaults_and_explicit_values() -> None:
    config = AgentConfig(model="test-model")
    loop = AgentLoop(config, MockAdapter([]), ToolRegistry())
    assert config.timeout_seconds == 300.0
    assert loop.bridge is None
    assert loop.agent_spec is None

    bridge = object()
    agent_spec = object()
    configured = AgentLoop(
        config,
        MockAdapter([]),
        ToolRegistry(),
        bridge=bridge,
        agent_spec=agent_spec,
    )
    assert configured.bridge is bridge
    assert configured.agent_spec is agent_spec


@pytest.mark.asyncio
async def test_run_without_tool_calls_returns_assistant_message() -> None:
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        MockAdapter([LLMResponse(content="hello", provider_metadata={"reasoning_content": "step"})]),
        ToolRegistry(),
    )
    result = await loop.run("hi")
    assert result.role == "assistant"
    assert result.content == "hello"
    assert result.provider_metadata["reasoning_content"] == "step"
    assert loop.status == "done"


@pytest.mark.asyncio
async def test_run_with_tool_calls_then_final_answer() -> None:
    async def echo_tool(_: dict[str, object]) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", output="tool-ok")

    registry = ToolRegistry()
    registry.register(_tool_def("echo"), echo_tool)
    responses = [
        LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={"x": 1})]),
        LLMResponse(content="final answer"),
    ]
    adapter = MockAdapter(responses)
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, registry)
    result = await loop.run("use tool")
    assert result.content == "final answer"
    assert len(adapter.requests) == 2
    assert any(msg.role == "tool" for msg in loop.messages)


@pytest.mark.asyncio
async def test_run_raises_on_max_iterations() -> None:
    async def no_op(_: dict[str, object]) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("echo"), no_op)
    loop = AgentLoop(
        AgentConfig(model="test-model", max_iterations=1),
        MockAdapter([LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={})])]),
        registry,
    )
    with pytest.raises(AgentError, match="LOOP_MAX_ITERATIONS"):
        await loop.run("loop")


@pytest.mark.asyncio
async def test_abort_interrupts_loop() -> None:
    async def no_op(_: dict[str, object]) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("echo"), no_op)
    loop = AgentLoop(
        AgentConfig(model="test-model", max_iterations=2),
        MockAdapter([LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={})])]),
        registry,
    )
    loop.abort()
    with pytest.raises(AgentError, match="LOOP_ABORTED"):
        await loop.run("stop")


@pytest.mark.asyncio
async def test_events_emitted_for_status_and_tools() -> None:
    async def no_op(_: dict[str, object]) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("echo"), no_op)
    adapter = MockAdapter(
        [
            LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={})]),
            LLMResponse(content="done"),
        ]
    )
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, registry)
    events: list[tuple[str, str]] = []
    loop.on(lambda event: events.append((event.type, str(event.data))))
    await loop.run("go")
    event_types = [item[0] for item in events]
    assert "status_change" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types


@pytest.mark.asyncio
async def test_run_adds_recovery_context_after_three_tool_failures() -> None:
    async def failing_tool(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="PermissionError [WinError 5] access denied", is_error=True)

    registry = ToolRegistry()
    registry.register(_tool_def("bash"), failing_tool)
    adapter = MockAdapter(
        [
            LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="bash", arguments={"command": "dir"})]),
            LLMResponse(content="", tool_calls=[ToolCall(id="tc_2", name="bash", arguments={"command": "dir /a"})]),
            LLMResponse(content="", tool_calls=[ToolCall(id="tc_3", name="bash", arguments={"command": "cd && dir"})]),
            LLMResponse(content="changed strategy"),
        ]
    )
    loop = AgentLoop(AgentConfig(model="test-model", max_consecutive_tool_failures=3), adapter, registry)
    result = await loop.run("check directory")
    tool_outputs = [
        result.output
        for message in loop.messages
        for result in (message.tool_results or [])
    ]
    assert result.content == "changed strategy"
    assert any("[失败恢复提示]" in output for output in tool_outputs)
    assert any("失败指纹" in output for output in tool_outputs)
    assert loop.status == "done"
    assert len(adapter.requests) == 4


@pytest.mark.asyncio
async def test_run_emits_structured_logs_with_shared_trace_id(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    setup_logging("INFO")
    loop = AgentLoop(
        AgentConfig(model="test-model", session_id="session-1"),
        MockAdapter([LLMResponse(content="hello")]),
        ToolRegistry(),
    )
    await loop.run("hi")
    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"component": "agent_loop"' in line
    ]
    assert len(lines) >= 3
    assert len({line["trace_id"] for line in lines}) == 1
    assert {line["session_id"] for line in lines} == {"session-1"}
    assert all("worker_id" in line for line in lines)


@pytest.mark.asyncio
async def test_run_increments_agent_runs_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_incr(metric: str, value: int = 1) -> None:
        calls.append((metric, value))

    monkeypatch.setattr("backend.core.s01_agent_loop.agent_loop_run.incr", fake_incr)
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        MockAdapter([LLMResponse(content="hello")]),
        ToolRegistry(),
    )
    await loop.run("hi")
    assert ("agent_runs", 1) in calls
