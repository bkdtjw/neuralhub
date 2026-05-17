from __future__ import annotations

from pathlib import Path

import pytest

from backend.common.types import LLMResponse, Message
from backend.core.s06_context_compression import LayeredCompressor, LayeredCompressorConfig


class SummaryAdapter:
    async def complete(self, request: object) -> LLMResponse:
        return LLMResponse(content="保留 item_id=item-9；用户决定排除高价商品，因为预算有限。")


@pytest.mark.asyncio
async def test_level3_summarizes_and_archives_p1_p2(tmp_path: Path) -> None:
    old = [
        Message(role="user", content="商品 item_id=item-9，用户决定排除高价商品，因为预算有限。"),
        Message(role="assistant", content="已记录决策。"),
    ]
    recent = [Message(role="user", content=f"recent {index}") for index in range(6)]
    compressor = LayeredCompressor(
        SummaryAdapter(),  # type: ignore[arg-type]
        "model",
        LayeredCompressorConfig(
            threshold_l2=1.0,
            threshold_l3=0.0,
            sessions_dir=str(tmp_path),
            session_id="sid",
        ),
    )

    compacted = await compressor.summarize_and_archive(
        [Message(role="system", content="system"), *old, *recent]
    )

    summary = compacted[1].content
    assert "item_id=item-9" in summary
    assert "用户决定排除高价商品" in summary
    archive_path = summary.rsplit("[无损备份]\n", 1)[1]
    assert Path(archive_path).exists()
