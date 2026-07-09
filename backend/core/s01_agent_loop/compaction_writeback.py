from __future__ import annotations

from typing import TYPE_CHECKING

from backend.common.logging import get_logger
from backend.common.types import Message

if TYPE_CHECKING:
    from backend.common.types import ToolDefinition

    from .agent_loop import AgentLoop

logger = get_logger(component="compaction_writeback")


def reattach_concurrent_messages(
    compacted: list[Message],
    messages: list[Message],
    snapshot_len: int,
) -> list[Message]:
    """把压缩 await 期间被并发 run 追加到 messages 尾部（索引 >= snapshot_len）的消息接回。

    压缩器基于进入时的整表快照生成 compacted，直接整表覆盖会丢掉 await 期间追加的尾部消息。
    这里把 messages[snapshot_len:] 接回 compacted 末尾；若兜底路径返回了实时整表而已包含这些
    消息，则按消息 id 去重，避免重复。
    """
    appended = messages[snapshot_len:]
    if not appended:
        return compacted
    existing_ids = {message.id for message in compacted}
    tail = [message for message in appended if message.id not in existing_ids]
    return compacted + tail


async def apply_layered_compaction(
    loop: AgentLoop,
    messages: list[Message],
    tool_definitions: list[ToolDefinition],
) -> None:
    """三层压缩（L2 归档 / L3 摘要 / 兜底整表压缩），就地写回 messages。

    每处在自身 await 前记录 snapshot_len，写回时用 reattach_concurrent_messages 保住 await
    期间被并发追加的尾部消息。三处顺序执行、前一处会改变 len，故各自重新取 snapshot_len。

    压缩是尽力而为：各层压缩器内部已各自兜错并回退原列表；此处再包一层，任何意外失败都只记
    日志并保留当前（仍合法配对的）messages，绝不打断 agent run。
    """
    try:
        snapshot_len = len(messages)
        compacted = await loop._layered_compressor.check_and_compact(messages, tool_definitions)
        messages[:] = reattach_concurrent_messages(compacted, messages, snapshot_len)
        snapshot_len = len(messages)
        summarized = await loop._layered_compressor.summarize_and_archive(messages, tool_definitions)
        messages[:] = reattach_concurrent_messages(summarized, messages, snapshot_len)
        estimated_tokens = loop._token_counter.estimate_messages_tokens(messages)
        estimated_tokens += loop._token_counter.estimate_tools_tokens(tool_definitions)
        if loop._compressor.policy.should_compact(estimated_tokens):
            loop._set_status("compacting")
            snapshot_len = len(messages)
            compacted = await loop._compressor.compact(messages)
            messages[:] = reattach_concurrent_messages(compacted, messages, snapshot_len)
            loop._set_status("thinking")
    except Exception:  # noqa: BLE001
        logger.warning("layered_compaction_failed", exc_info=True)


__all__ = ["apply_layered_compaction", "reattach_concurrent_messages"]
