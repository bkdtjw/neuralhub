from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from backend.common.types import Message, ToolCall, ToolResult
from backend.core.s06_context_compression.level2_compact import (
    RECENT_KEEP_COUNT,
    compact_oldest_large_tool_result,
)
from backend.core.s06_context_compression.level3_summary import (
    SUMMARY_MARKER,
    _summary_prompt,
)


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


def _large_output(tag: str) -> str:
    # token_count 对纯 ASCII 仍约为 len//4，需 >500 才判大结果，故 >2000 字符；不含 data/ 归档路径。
    return f"{tag} " + ("x" * 3000)


def test_l2_protects_recent_tail_from_archiving(tmp_path: Path) -> None:
    big_head = _large_output("HEAD")
    big_tail = _large_output("TAIL")
    head = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc_head", name="Search", arguments={})],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="tc_head", output=big_head)],
        ),
    ]
    tail = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc_tail", name="Search", arguments={})],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="tc_tail", output=big_tail)],
        ),
        *[Message(role="user", content=f"recent {index}") for index in range(RECENT_KEEP_COUNT - 2)],
    ]
    messages = [*head, *tail]
    assert len(tail) == RECENT_KEEP_COUNT

    compacted, changed = compact_oldest_large_tool_result(messages, str(tmp_path), "sid")

    assert changed is True
    head_result = compacted[1].tool_results[0]  # type: ignore[index]
    assert "完整结果:" in head_result.output
    assert len(head_result.output) < len(big_head)
    assert head_result.artifacts
    assert Path(head_result.artifacts[0].path).exists()

    tail_result = compacted[3].tool_results[0]  # type: ignore[index]
    assert tail_result.output == big_tail
    assert not tail_result.artifacts


def test_l2_no_archive_when_at_recent_keep_boundary(tmp_path: Path) -> None:
    big = _large_output("SMALLSET")
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc", name="Search", arguments={})],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="tc", output=big)],
        ),
        *[Message(role="user", content=f"m{index}") for index in range(RECENT_KEEP_COUNT - 2)],
    ]
    assert len(messages) == RECENT_KEEP_COUNT

    compacted, changed = compact_oldest_large_tool_result(messages, str(tmp_path), "sid")

    assert changed is False
    assert compacted[1].tool_results[0].output == big  # type: ignore[index]
    assert list(tmp_path.rglob("*.json")) == []


def test_l3_incremental_prompt_keeps_existing_summary_untruncated() -> None:
    tail_marker = "END_SUMMARY_7a3f"
    existing = Message(
        role="user",
        content=f"{SUMMARY_MARKER}\n" + ("历史正文行。" * 300) + tail_marker,
    )
    regular_marker = "END_REGULAR_9c1d"
    regular = Message(role="user", content=("普通历史行。" * 300) + regular_marker)

    prompt = _summary_prompt([existing, regular])

    # 既有摘要整段原样保留，并置于历史顶部作为“已有摘要”上下文
    assert "[已有摘要]" in prompt
    assert tail_marker in prompt
    assert prompt.index(tail_marker) < prompt.index("[历史开始]")
    # 普通消息仍被 _clip 截断
    assert "[truncated" in prompt
    assert regular_marker not in prompt
