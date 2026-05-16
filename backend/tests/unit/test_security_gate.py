from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    SecurityPolicy,
    SignedToolCall,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    ToolPermission,
    ToolResult,
)
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s01_agent_loop.user_config_store import UserConfig, UserConfigStore
from backend.core.s02_tools import ToolExecutor, ToolRegistry
from backend.core.s02_tools.security_gate import SecurityGate


class MockAdapter(LLMAdapter):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self._index = 0
        self.requests: list[LLMRequest] = []

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._index >= len(self._responses):
            return LLMResponse(content="")
        response = self._responses[self._index]
        self._index += 1
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


def _tool_def(name: str, *, requires_approval: bool = False) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        category="shell",
        parameters=ToolParameterSchema(),
        permission=ToolPermission(requires_approval=requires_approval),
    )


def _registry_with_echo() -> ToolRegistry:
    async def _echo(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("echo"), _echo)
    return registry


def _policy(**kwargs: object) -> SecurityPolicy:
    return SecurityPolicy(**{"allowed_tools": [], "dangerous_tools": [], **kwargs})


def test_authorize_and_verify_success() -> None:
    gate = SecurityGate(_policy(), _registry_with_echo())
    result = gate.authorize([ToolCall(id="call-1", name="echo", arguments={"x": 1})])
    assert len(result.signed_calls) == 1 and result.rejected_results == []
    assert gate.verify(result.signed_calls[0]) is True


def test_verify_detects_tampered_signature() -> None:
    gate = SecurityGate(_policy(), _registry_with_echo())
    signed_call = gate.authorize(
        [ToolCall(id="call-1", name="echo", arguments={"x": 1})]
    ).signed_calls[0]
    tampered = signed_call.model_copy(
        deep=True,
        update={"tool_call": signed_call.tool_call.model_copy(update={"arguments": {"x": 2}})},
    )
    assert gate.verify(tampered) is False


def test_verify_blocks_replay() -> None:
    gate = SecurityGate(_policy(), _registry_with_echo())
    signed_call = gate.authorize(
        [ToolCall(id="call-1", name="echo", arguments={"x": 1})]
    ).signed_calls[0]
    assert gate.verify(signed_call) is True
    assert gate.verify(signed_call) is False


def test_authorize_rejects_non_whitelisted_tool() -> None:
    gate = SecurityGate(_policy(allowed_tools=["Read"]), _registry_with_echo())
    result = gate.authorize([ToolCall(id="call-1", name="echo", arguments={})])
    assert result.signed_calls == []
    assert result.rejected_results[0].tool_call_id == "call-1"
    assert "tool not allowed" in result.rejected_results[0].output


def test_authorize_rejects_unknown_tool() -> None:
    gate = SecurityGate(_policy(), ToolRegistry())
    result = gate.authorize([ToolCall(id="call-1", name="missing", arguments={})])
    assert result.signed_calls == []
    assert "unknown tool" in result.rejected_results[0].output


def test_authorize_respects_max_calls_per_turn() -> None:
    gate = SecurityGate(_policy(max_calls_per_turn=2), _registry_with_echo())
    result = gate.authorize(
        [
            ToolCall(id="call-1", name="echo", arguments={"x": 1}),
            ToolCall(id="call-2", name="echo", arguments={"x": 2}),
            ToolCall(id="call-3", name="echo", arguments={"x": 3}),
        ]
    )
    assert [item.sequence for item in result.signed_calls] == [1, 2]
    assert result.rejected_results[0].tool_call_id == "call-3"
    assert "max calls per turn exceeded" in result.rejected_results[0].output


def test_authorize_routes_requires_approval_to_pending() -> None:
    async def _execute(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="should not run")

    registry = ToolRegistry()
    registry.register(_tool_def("approval_tool", requires_approval=True), _execute)
    gate = SecurityGate(_policy(allowed_tools=["approval_tool"]), registry)
    call = ToolCall(id="call-1", name="approval_tool", arguments={})

    result = gate.authorize([call])

    assert result.pending_approval == [call]
    assert result.signed_calls == []
    assert result.rejected_results == []


def test_authorize_splits_mixed_approval_and_signed_calls() -> None:
    async def _execute(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("approval_tool", requires_approval=True), _execute)
    registry.register(_tool_def("echo"), _execute)
    gate = SecurityGate(_policy(), registry)

    result = gate.authorize(
        [
            ToolCall(id="call-1", name="approval_tool", arguments={}),
            ToolCall(id="call-2", name="echo", arguments={}),
        ]
    )

    assert [call.id for call in result.pending_approval] == ["call-1"]
    assert [item.tool_call.id for item in result.signed_calls] == ["call-2"]
    assert result.rejected_results == []


def test_force_sign_bypasses_approval_requirement() -> None:
    async def _execute(_: dict[str, object]) -> ToolResult:
        return ToolResult(output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("approval_tool", requires_approval=True), _execute)
    gate = SecurityGate(_policy(), registry)
    call = ToolCall(id="call-1", name="approval_tool", arguments={})

    signed = gate.force_sign([call])

    assert len(signed) == 1
    assert signed[0].tool_call == call
    assert gate.verify(signed[0]) is True


@pytest.mark.asyncio
async def test_execute_signed_rejects_invalid_signature() -> None:
    registry = _registry_with_echo()
    gate = SecurityGate(_policy(), registry)
    executor = ToolExecutor(registry)
    signed_call = gate.authorize([ToolCall(id="call-1", name="echo", arguments={})]).signed_calls[0]
    forged = SignedToolCall(
        tool_call=signed_call.tool_call,
        sequence=signed_call.sequence,
        timestamp=signed_call.timestamp,
        signature="deadbeef",
    )
    result = await executor.execute_signed(forged, gate)
    assert result.is_error is True and result.output == "HMAC verification failed"


def test_reset_resets_sequence_counter() -> None:
    gate = SecurityGate(_policy(), _registry_with_echo())
    first = gate.authorize([ToolCall(id="call-1", name="echo", arguments={})]).signed_calls[0]
    gate.reset()
    second = gate.authorize([ToolCall(id="call-2", name="echo", arguments={})]).signed_calls[0]
    assert first.sequence == 1 and second.sequence == 1


@pytest.mark.asyncio
async def test_agent_loop_emits_security_reject_event() -> None:
    registry = _registry_with_echo()
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        MockAdapter(
            [
                LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="call-1", name="echo", arguments={"x": 1})],
                ),
                LLMResponse(content="done"),
            ]
        ),
        registry,
        security_policy=SecurityPolicy(allowed_tools=["Read"], dangerous_tools=[]),
    )
    events: list[tuple[str, object]] = []
    loop.on(lambda event: events.append((event.type, event.data)))
    result = await loop.run("run tool")
    security_event = next(item for item in events if item[0] == "security_reject")
    assert result.content == "done"
    assert isinstance(security_event[1], ToolResult)
    assert "SecurityGate rejected" in security_event[1].output


@pytest.mark.asyncio
async def test_agent_loop_executes_tool_after_manual_approval() -> None:
    executed = False

    async def approval_tool(_: dict[str, object]) -> ToolResult:
        nonlocal executed
        executed = True
        return ToolResult(output="approved")

    registry = ToolRegistry()
    registry.register(_tool_def("approval_tool", requires_approval=True), approval_tool)
    adapter = MockAdapter(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call-1", name="approval_tool", arguments={})],
            ),
            LLMResponse(content="done"),
        ]
    )
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, registry)
    events: list[tuple[str, object]] = []

    def handle_event(event: object) -> None:
        events.append((event.type, event.data))
        if getattr(event, "type", "") == "tool_approval_required":
            loop.approve_tool_call("call-1")

    loop.on(handle_event)

    result = await loop.run("run tool")

    tool_message = next(message for message in loop.messages if message.role == "tool")
    assert result.content == "done"
    assert executed is True
    assert tool_message.tool_results is not None
    assert tool_message.tool_results[0].tool_call_id == "call-1"
    assert tool_message.tool_results[0].is_error is False
    assert tool_message.tool_results[0].output == "approved"
    assert adapter.requests[1].messages[-1].tool_results is not None
    assert adapter.requests[1].messages[-1].tool_results[0].tool_call_id == "call-1"
    assert any(item[0] == "tool_approval_required" for item in events)
    assert any(item[0] == "tool_result" for item in events)
    assert not any(item[0] == "security_reject" for item in events)


@pytest.mark.asyncio
async def test_agent_loop_auto_approves_tool_after_review(tmp_path) -> None:
    executed = False

    async def approval_tool(_: dict[str, object]) -> ToolResult:
        nonlocal executed
        executed = True
        return ToolResult(output="approved")

    registry = ToolRegistry()
    registry.register(_tool_def("approval_tool", requires_approval=True), approval_tool)
    adapter = MockAdapter(
        [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call-1", name="approval_tool", arguments={})],
            ),
            LLMResponse(
                content='[{"decision":"auto_approve","reason":"一致","risk_level":"low"}]'
            ),
            LLMResponse(content="done"),
        ]
    )
    store = UserConfigStore(tmp_path / "user_configs")
    store.save(UserConfig(owner_id="owner-1", auto_approve_tools=True))
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        adapter,
        registry,
        owner_id="owner-1",
        user_config_store=store,
    )
    events: list[str] = []
    loop.on(lambda event: events.append(event.type))

    result = await loop.run("run tool")

    assert result.content == "done"
    assert executed is True
    assert "tool_approval_required" not in events
