from __future__ import annotations

import re

from backend.common.types import Message, ToolResult

RECENT_KEEP_COUNT = 6
_PATH_RE = re.compile(r"(data/(?:artifacts|sessions|steps)/[^\s]+)")
_IDENTIFIER_RE = re.compile(
    r"(?:item_id|shop_id|order_id|商品ID|订单号)[:=：]\s*[^\s,，;；]+|"
    r"https?://[^\s]+|¥[^¥\s]+¥"
)


def compact_old_tool_summaries(messages: list[Message]) -> list[Message]:
    if len(messages) <= RECENT_KEEP_COUNT:
        return list(messages)
    old = messages[:-RECENT_KEEP_COUNT]
    recent = messages[-RECENT_KEEP_COUNT:]
    return [*_compact_messages(old), *recent]


def _compact_messages(messages: list[Message]) -> list[Message]:
    result: list[Message] = []
    for message in messages:
        if message.role != "tool" or not message.tool_results:
            result.append(message)
            continue
        result.append(message.model_copy(update={"tool_results": _compact_results(message)}))
    return result


def _compact_results(message: Message) -> list[ToolResult]:
    return [
        result.model_copy(update={"output": _compact_output(result.output)})
        for result in message.tool_results or []
    ]


def _compact_output(output: str) -> str:
    path = _first_match(_PATH_RE, output)
    if not path:
        return output
    identifiers = sorted(set(match.group(0) for match in _IDENTIFIER_RE.finditer(output)))
    lines = ["[工具结果已归档]", f"完整结果: {path}"]
    if identifiers:
        lines.append("保留标识符: " + ", ".join(identifiers[:20]))
    return "\n".join(lines)


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1) if match else ""
