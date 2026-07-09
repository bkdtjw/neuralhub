from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.common.types import (
    Message,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    ToolResult,
)
from backend.core.s06_context_compression import LayeredCompressor, LayeredCompressorConfig


class NoopAdapter:
    async def complete(self, request: object) -> object:
        raise AssertionError("Level 2 must not call the LLM")


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        category="file-ops",
        parameters=ToolParameterSchema(),
    )


@pytest.mark.asyncio
async def test_level2_archives_oldest_large_tool_result_on_threshold(tmp_path: Path) -> None:
    output = json.dumps(
        [{"item_id": f"abc-{index}", "name": f"商品{index}"} for index in range(300)],
        ensure_ascii=False,
    )
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc1", name="Search", arguments={})],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="tc1", output=output)],
        ),
        # 让大工具结果落在受保护的最近 6 条之外，才会进入可归档区
        *[Message(role="user", content=f"recent {index}") for index in range(6)],
    ]
    compressor = LayeredCompressor(
        NoopAdapter(),  # type: ignore[arg-type]
        "model",
        LayeredCompressorConfig(threshold_l2=0.0, threshold_l3=1.0, artifacts_dir=str(tmp_path)),
    )

    compacted = await compressor.check_and_compact(messages, [_tool("read_history")])

    result = compacted[1].tool_results[0]  # type: ignore[index]
    assert "完整结果:" in result.output
    assert len(result.output) < len(output)
    assert result.artifacts
    assert Path(result.artifacts[0].path).exists()


@pytest.mark.asyncio
async def test_level2_skips_tool_results_without_read_history(tmp_path: Path) -> None:
    output = "x" * 3000
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tc1", name="Search", arguments={})],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="tc1", output=output)],
        ),
    ]
    compressor = LayeredCompressor(
        NoopAdapter(),  # type: ignore[arg-type]
        "model",
        LayeredCompressorConfig(threshold_l2=0.0, threshold_l3=1.0, artifacts_dir=str(tmp_path)),
    )

    compacted = await compressor.check_and_compact(messages, [_tool("Search")])

    assert compacted[1].tool_results[0].output == output  # type: ignore[index]
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.asyncio
async def test_level2_never_archives_history_lookup_reads(tmp_path: Path) -> None:
    output = "history detail\n" * 300
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="Read",
                    arguments={"path": "data/artifacts/sid/search.json"},
                )
            ],
        ),
        Message(
            role="tool",
            content="",
            tool_results=[ToolResult(tool_call_id="tc1", output=output)],
        ),
    ]
    compressor = LayeredCompressor(
        NoopAdapter(),  # type: ignore[arg-type]
        "model",
        LayeredCompressorConfig(threshold_l2=0.0, threshold_l3=1.0, artifacts_dir=str(tmp_path)),
    )

    compacted = await compressor.check_and_compact(messages, [_tool("read_history")])

    assert compacted[1].tool_results[0].output == output  # type: ignore[index]
    assert list(tmp_path.rglob("*.json")) == []
