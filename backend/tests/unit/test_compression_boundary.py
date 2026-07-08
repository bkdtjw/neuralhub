from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    Message,
    StreamChunk,
    ToolCall,
    ToolResult,
)
from backend.core.s01_agent_loop.agent_loop_support import build_llm_request
from backend.core.s06_context_compression import (
    ContextCompressor,
    ThresholdPolicy,
    align_recent_boundary,
)
from backend.core.s06_context_compression.level3_summary import (
    SummaryArchiveRequest,
    summarize_archive,
)


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


class _MockAdapter(LLMAdapter):
    def __init__(self, summary: str) -> None:
        self._summary = summary

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self._summary)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:  # pragma: no cover - 满足抽象签名
            yield StreamChunk(type="done")


def _round(index: int) -> list[Message]:
    call_id = f"call_{index}"
    return [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=call_id, name="Read", arguments={"path": f"f{index}.py"})],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id=call_id, output=f"result {index}")],
        ),
    ]


def _build_conversation() -> list[Message]:
    messages = [
        Message(role="system", content="system prompt"),
        Message(role="user", content="do the task"),
    ]
    for index in range(1, 5):  # 4 轮 assistant(tool_calls)/tool(tool_results)
        messages.extend(_round(index))
    messages.append(Message(role="assistant", content="final answer"))
    return messages


def _assert_no_orphan_tool(messages: list[Message]) -> None:
    available: set[str] = set()
    for message in messages:
        for call in message.tool_calls or []:
            available.add(call.id)
        for result in message.tool_results or []:
            assert result.tool_call_id in available, f"orphan tool_result {result.tool_call_id}"


def _recent_part(messages: list[Message]) -> list[Message]:
    # compact / summarize_archive 返回 [system, summary(user), *recent]
    return messages[2:]


# --- align_recent_boundary 边界 ---


def test_align_recent_boundary_reserve_zero_keeps_all_in_old() -> None:
    non_system = [Message(role="user", content="hi"), Message(role="assistant", content="yo")]
    old, recent = align_recent_boundary(non_system, 0)
    assert recent == []
    assert old == non_system


def test_align_recent_boundary_moves_leading_orphan_tool_to_old() -> None:
    non_system = [message for message in _build_conversation() if message.role != "system"]
    old, recent = align_recent_boundary(non_system, 6)
    assert recent[0].role != "tool"
    assert old[-1].role == "tool"
    _assert_no_orphan_tool(old)
    _assert_no_orphan_tool(recent)


def test_align_recent_boundary_all_tool_recent_drains_to_old() -> None:
    non_system = [
        Message(role="tool", content="", tool_results=[ToolResult(tool_call_id="a", output="x")]),
        Message(role="tool", content="", tool_results=[ToolResult(tool_call_id="b", output="y")]),
        Message(role="tool", content="", tool_results=[ToolResult(tool_call_id="c", output="z")]),
    ]
    old, recent = align_recent_boundary(non_system, 3)
    assert recent == []
    assert len(old) == 3


def test_align_recent_boundary_no_tool_untouched() -> None:
    non_system = [
        Message(role="user", content="a"),
        Message(role="assistant", content="b"),
        Message(role="user", content="c"),
        Message(role="assistant", content="d"),
    ]
    old, recent = align_recent_boundary(non_system, 2)
    assert [message.content for message in old] == ["a", "b"]
    assert [message.content for message in recent] == ["c", "d"]


# --- compact / summarize_archive 集成 ---


@pytest.mark.asyncio
async def test_compact_keeps_tool_pairs_intact() -> None:
    compressor = ContextCompressor(
        adapter=_MockAdapter("SUMMARY"),
        model="test-model",
        policy=ThresholdPolicy(),  # 默认 reserve = 6
    )
    result = await compressor.compact(_build_conversation())
    _assert_no_orphan_tool(result)
    recent = _recent_part(result)
    assert recent[0].role != "tool"
    assert result[0].role == "system"
    assert result[1].content == "[对话历史摘要]\nSUMMARY"


@pytest.mark.asyncio
async def test_summarize_archive_keeps_tool_pairs_intact(tmp_path) -> None:
    request = SummaryArchiveRequest(
        messages=_build_conversation(),
        adapter=_MockAdapter("ARCHIVE SUMMARY"),
        model="test-model",
        sessions_dir=str(tmp_path),
        session_id="session-1",
    )
    result = await summarize_archive(request)
    _assert_no_orphan_tool(result)
    recent = _recent_part(result)
    assert recent[0].role != "tool"
    assert result[0].role == "system"
    assert result[1].content.startswith("[对话历史摘要]\nARCHIVE SUMMARY")


# --- 发送路径自愈 ---


def test_build_llm_request_drops_orphan_tool_from_recent() -> None:
    # 内存历史被污染：recent 首条是孤儿 tool（配对 assistant 已丢失）。
    polluted = [
        Message(role="system", content="sys"),
        Message(role="user", content="[对话历史摘要]\nprev summary"),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="ghost", output="stale")],
        ),
        Message(role="user", content="continue"),
    ]
    request = build_llm_request(AgentConfig(model="test-model"), polluted, [])
    roles = [message.role for message in request.recent_messages]
    assert "tool" not in roles
    assert any(
        message.role == "user" and message.content == "continue"
        for message in request.recent_messages
    )
