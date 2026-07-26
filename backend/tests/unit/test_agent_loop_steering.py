"""边跑边聊：运行中排队的用户消息在迭代边界注入，收尾前有排队消息则继续对话。"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable

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
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s01_agent_loop.message_queue import PendingMessageQueue
from backend.core.s02_tools.registry import ToolRegistry


class SteeringAdapter(LLMAdapter):
    """在指定次序的 LLM 调用时触发回调，模拟用户运行中插话。"""

    def __init__(
        self,
        responses: list[LLMResponse],
        on_call: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []
        self._on_call = on_call or {}

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        index = len(self.requests)
        self.requests.append(request)
        hook = self._on_call.get(index)
        if hook is not None:
            hook()
        if index >= len(self.responses):
            return LLMResponse(content="")
        return self.responses[index]

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


def _user_contents(request: LLMRequest) -> list[str]:
    return [msg.content for msg in request.messages if msg.role == "user"]


def test_pending_queue_strips_and_drains() -> None:
    queue = PendingMessageQueue()
    queue.push("  第一条  ")
    queue.push("   ")
    queue.push("第二条")
    assert len(queue) == 2
    assert queue.drain() == ["第一条", "第二条"]
    assert len(queue) == 0
    assert queue.drain() == []


@pytest.mark.asyncio
async def test_steer_injected_before_next_iteration() -> None:
    async def echo_tool(_: dict[str, object]) -> ToolResult:
        return ToolResult(tool_call_id="tc_1", output="tool-ok")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="echo", description="echo", category="shell", parameters=ToolParameterSchema()),
        echo_tool,
    )
    loop: AgentLoop | None = None
    adapter = SteeringAdapter(
        [
            LLMResponse(content="", tool_calls=[ToolCall(id="tc_1", name="echo", arguments={})]),
            LLMResponse(content="最终答复"),
        ],
        # 第一次 LLM 调用期间用户插话（子 agent/工具还在跑）
        on_call={0: lambda: loop.queue_user_message("补充：重点看安全性")},
    )
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, registry)

    result = await loop.run("初始任务")

    assert result.content == "最终答复"
    assert "补充：重点看安全性" in _user_contents(adapter.requests[1])
    assert "补充：重点看安全性" not in _user_contents(adapter.requests[0])


@pytest.mark.asyncio
async def test_steer_at_final_answer_continues_run() -> None:
    loop: AgentLoop | None = None
    adapter = SteeringAdapter(
        [
            LLMResponse(content="第一版结论"),
            LLMResponse(content="修订后的结论"),
        ],
        # 模型正生成收尾答复时用户插话：不应结束本轮 run
        on_call={0: lambda: loop.queue_user_message("再对比一下方案 B")},
    )
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, ToolRegistry())

    result = await loop.run("初始任务")

    assert result.content == "修订后的结论"
    assert len(adapter.requests) == 2
    assert "再对比一下方案 B" in _user_contents(adapter.requests[1])
    # 第一版结论作为中间 assistant 消息保留在历史里
    assert any(msg.role == "assistant" and msg.content == "第一版结论" for msg in loop.messages)
    assert loop.status == "done"


@pytest.mark.asyncio
async def test_leftover_steer_prepended_on_next_run() -> None:
    adapter = SteeringAdapter([LLMResponse(content="好的")])
    loop = AgentLoop(AgentConfig(model="test-model"), adapter, ToolRegistry())
    # 上一轮 run 收尾竞态残留的排队消息
    loop.queue_user_message("上轮没赶上的补充")

    await loop.run("新问题")

    contents = _user_contents(adapter.requests[0])
    assert contents.index("上轮没赶上的补充") < contents.index("新问题")
