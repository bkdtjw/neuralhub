from __future__ import annotations

from backend.common.types import Message


def align_recent_boundary(
    non_system: list[Message],
    reserve: int,
) -> tuple[list[Message], list[Message]]:
    """按 reserve 条数切出 (old, recent)，并把 recent 首部的孤儿 tool 消息回退到 old。

    固定条数硬切会把 assistant(tool_calls) 与配对的 tool(tool_results) 拆开，
    让 recent 首条变成没有前置 tool_calls 的孤儿 tool_result，经 Anthropic/OpenAI
    转换后触发 400。这里把首部孤儿 tool 逐条回退到 old 末尾（保持顺序），
    保证 recent 内每个 tool_result 都能在 recent 的 tool_calls 找到配对。
    """
    if reserve <= 0:
        return list(non_system), []
    recent = non_system[-reserve:]
    old = non_system[: len(non_system) - len(recent)]
    # recent 首条是 tool 即孤儿：其配对 assistant 必然已被切进 old。
    while recent and recent[0].role == "tool":
        old.append(recent.pop(0))
    # 加固：万一 recent 内仍有 tool_result 的 id 在 recent 找不到配对，继续前移直到自洽。
    while recent and not _tool_results_paired(recent):
        old.append(recent.pop(0))
    return old, recent


def _tool_results_paired(recent: list[Message]) -> bool:
    available: set[str] = set()
    for message in recent:
        for call in message.tool_calls or []:
            available.add(call.id)
        for result in message.tool_results or []:
            if result.tool_call_id not in available:
                return False
    return True


__all__ = ["align_recent_boundary"]
