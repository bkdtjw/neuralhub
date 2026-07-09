from __future__ import annotations

from backend.common.types import Message, ToolResult


def build_orphan_tool_results(message: Message) -> list[ToolResult]:
    return [
        ToolResult(
            tool_call_id=call.id,
            output="[error] tool execution failed, no response captured",
            is_error=True,
        )
        for call in message.tool_calls or []
    ]


def patch_orphan_tool_calls(messages: list[Message]) -> list[Message]:
    if not messages:
        return messages
    last = messages[-1]
    if last.role != "assistant" or not last.tool_calls:
        return messages
    messages.append(Message(role="tool", content="", tool_results=build_orphan_tool_results(last)))
    return messages


__all__ = ["build_orphan_tool_results", "patch_orphan_tool_calls"]
