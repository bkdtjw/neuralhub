from __future__ import annotations

import pytest

from backend.common.types import Message, ToolResult
from backend.core.s06_context_compression import LayeredCompressor, LayeredCompressorConfig


class NoopAdapter:
    async def complete(self, request: object) -> object:
        raise AssertionError("Level 2 must not call the LLM")


@pytest.mark.asyncio
async def test_level2_compacts_old_tool_summary_to_path_reference() -> None:
    old_tool = Message(
        role="tool",
        content="",
        tool_results=[
            ToolResult(
                output=(
                    "[工具结果摘要]\nitem_id: abc123\n价格 10\n"
                    "完整结果: data/artifacts/sid/search.json"
                )
            )
        ],
    )
    recent = [Message(role="user", content=f"recent {index}") for index in range(6)]
    compressor = LayeredCompressor(
        NoopAdapter(),  # type: ignore[arg-type]
        "model",
        LayeredCompressorConfig(threshold_l2=0.0, threshold_l3=1.0),
    )

    compacted = await compressor.check_and_compact([old_tool, *recent])

    output = compacted[0].tool_results[0].output  # type: ignore[index]
    assert output.startswith("[工具结果已归档]")
    assert "data/artifacts/sid/search.json" in output
    assert "item_id: abc123" in output
