from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import (
    AgentConfig,
    AgentEvent,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s02_tools.registry import ToolRegistry


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


class _MockAdapter(LLMAdapter):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self._index = 0

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self._index >= len(self._responses):
            return LLMResponse(content="")
        response = self._responses[self._index]
        self._index += 1
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:  # pragma: no cover - 满足抽象签名
            yield StreamChunk(type="done")


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name, description=name, category="shell", parameters=ToolParameterSchema()
    )


def _echo_registry() -> ToolRegistry:
    async def echo(_: dict[str, object]) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", output="ok")

    registry = ToolRegistry()
    registry.register(_tool_def("echo"), echo)
    return registry


@pytest.mark.asyncio
async def test_abort_then_run_executes_and_records_message() -> None:
    # 线上路径：同一 settings 复用同一 loop。用户在回答结束后点停止（loop 空闲，
    # abort 只置位 _aborted），下一条消息应正常执行，且用户消息进入历史，不误报 LOOP_ABORTED。
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        _MockAdapter([LLMResponse(content="answer-1"), LLMResponse(content="answer-2")]),
        ToolRegistry(),
    )
    first = await loop.run("msg1")
    assert first.content == "answer-1"

    loop.abort()
    second = await loop.run("msg2")
    assert second.role == "assistant"
    assert second.content == "answer-2"
    assert any(msg.role == "user" and msg.content == "msg2" for msg in loop.messages)


@pytest.mark.asyncio
async def test_abort_set_during_run_stops_at_iteration_boundary() -> None:
    # 运行中置 _aborted（等价于 loop.abort() 的置位）应在迭代边界抛 LOOP_ABORTED 停止。
    loop = AgentLoop(
        AgentConfig(model="test-model", max_iterations=3),
        _MockAdapter(
            [LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={})])]
        ),
        _echo_registry(),
    )

    def _abort_on_tool_result(event: AgentEvent) -> None:
        if event.type == "tool_result":
            loop._aborted = True

    loop.on(_abort_on_tool_result)
    with pytest.raises(AgentError, match="LOOP_ABORTED"):
        await loop.run("go")


@pytest.mark.asyncio
async def test_cancellation_mid_iteration_patches_orphan_tool_calls() -> None:
    # 工具执行中途被 cancel（BaseException/CancelledError）：收尾应补齐孤儿 tool_calls，
    # 历史不以“带 tool_calls 无 tool_results 的 assistant”结尾，且 CancelledError 原样重抛。
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        _MockAdapter(
            [LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={})])]
        ),
        _echo_registry(),
    )

    def _cancel_on_tool_call(event: AgentEvent) -> None:
        if event.type == "tool_call":
            raise asyncio.CancelledError

    loop.on(_cancel_on_tool_call)
    with pytest.raises(asyncio.CancelledError):
        await loop.run("go")

    messages = loop.messages
    assert messages[-2].role == "assistant"
    assert messages[-2].tool_calls
    assert messages[-1].role == "tool"
    assert messages[-1].tool_results[0].tool_call_id == "tc_1"
    assert messages[-1].tool_results[0].is_error is True
