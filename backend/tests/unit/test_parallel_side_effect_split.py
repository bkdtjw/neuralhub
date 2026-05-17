from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from time import monotonic

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s01_agent_loop import AgentLoop
from backend.core.s02_tools import ToolRegistry


class MockAdapter(LLMAdapter):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self._index = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self._index >= len(self._responses):
            return LLMResponse(content="")
        response = self._responses[self._index]
        self._index += 1
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")

    async def test_connection(self) -> bool:
        return True


def _definition(name: str, *, side_effect: bool) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        category="search",
        parameters=ToolParameterSchema(),
        side_effect=side_effect,
    )


@pytest.mark.asyncio
async def test_read_only_tools_run_in_parallel_before_serial_writes() -> None:
    events: list[tuple[str, str, float]] = []
    registry = ToolRegistry()

    async def read_tool(args: dict[str, object]) -> ToolResult:
        name = str(args["name"])
        events.append(("start", name, monotonic()))
        await asyncio.sleep(0.05)
        events.append(("end", name, monotonic()))
        return ToolResult(output=name)

    async def write_tool(args: dict[str, object]) -> ToolResult:
        name = str(args["name"])
        events.append(("start", name, monotonic()))
        await asyncio.sleep(0.01)
        events.append(("end", name, monotonic()))
        return ToolResult(output=name)

    registry.register(_definition("read_tool", side_effect=False), read_tool)
    registry.register(_definition("write_tool", side_effect=True), write_tool)
    adapter = MockAdapter(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="read-1", name="read_tool", arguments={"name": "read-1"}),
                    ToolCall(id="write-1", name="write_tool", arguments={"name": "write-1"}),
                    ToolCall(id="read-2", name="read_tool", arguments={"name": "read-2"}),
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, registry)

    await loop.run("run tools")

    tool_results = [
        result.output
        for message in loop.messages
        for result in (message.tool_results or [])
    ]
    times = {(kind, name): value for kind, name, value in events}
    assert tool_results == ["read-1", "write-1", "read-2"]
    assert abs(times[("start", "read-1")] - times[("start", "read-2")]) < 0.05
    assert times[("start", "write-1")] >= times[("end", "read-1")]
    assert times[("start", "write-1")] >= times[("end", "read-2")]


@pytest.mark.asyncio
async def test_write_tools_execute_serially() -> None:
    events: list[tuple[str, str]] = []
    registry = ToolRegistry()

    async def write_tool(args: dict[str, object]) -> ToolResult:
        name = str(args["name"])
        events.append(("start", name))
        await asyncio.sleep(0.01)
        events.append(("end", name))
        return ToolResult(output=name)

    registry.register(_definition("write_tool", side_effect=True), write_tool)
    adapter = MockAdapter(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="w1", name="write_tool", arguments={"name": "w1"}),
                    ToolCall(id="w2", name="write_tool", arguments={"name": "w2"}),
                ],
            ),
            LLMResponse(content="done"),
        ]
    )
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, registry)

    await loop.run("run writes")

    assert events == [("start", "w1"), ("end", "w1"), ("start", "w2"), ("end", "w2")]
