from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.common.types import ToolResult
from backend.core.s06_context_compression import LayeredCompressor, LayeredCompressorConfig


class NoopAdapter:
    async def complete(self, request: object) -> object:
        raise AssertionError("Level 1 must not call the LLM")


@pytest.mark.asyncio
async def test_level1_sinks_large_tool_result_to_artifact(tmp_path: Path) -> None:
    output = json.dumps(
        [{"item_id": f"item-{index}", "name": f"商品{index}", "price": index} for index in range(300)],
        ensure_ascii=False,
    )
    compressor = LayeredCompressor(
        NoopAdapter(),  # type: ignore[arg-type]
        "model",
        LayeredCompressorConfig(artifacts_dir=str(tmp_path), session_id="sid"),
    )

    result = await compressor.process_tool_result(ToolResult(tool_call_id="tc1", output=output))

    assert "完整结果:" in result.output
    assert len(result.output) < len(output)
    assert result.artifacts
    assert Path(result.artifacts[0].path).exists()
