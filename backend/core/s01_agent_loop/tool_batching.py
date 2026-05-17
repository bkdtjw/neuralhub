from __future__ import annotations

from backend.common.types import SignedToolCall, ToolDefinition, ToolResult


def partition_by_side_effect(
    signed_calls: list[SignedToolCall],
    tools: list[ToolDefinition],
) -> tuple[list[SignedToolCall], list[SignedToolCall]]:
    by_name = {tool.name: tool for tool in tools}
    read_only: list[SignedToolCall] = []
    write: list[SignedToolCall] = []
    for signed_call in signed_calls:
        definition = by_name.get(signed_call.tool_call.name)
        target = read_only if definition is not None and not definition.side_effect else write
        target.append(signed_call)
    return read_only, write


def merge_results(
    read_results: list[ToolResult],
    write_results: list[ToolResult],
    signed_calls: list[SignedToolCall],
) -> list[ToolResult]:
    by_call_id = {
        result.tool_call_id: result
        for result in [*read_results, *write_results]
    }
    return [
        by_call_id[signed_call.tool_call.id]
        for signed_call in signed_calls
        if signed_call.tool_call.id in by_call_id
    ]


__all__ = ["merge_results", "partition_by_side_effect"]
