from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.common.types import LLMRequest, LLMResponse, LLMUsage, ToolCall, merge_usage

if TYPE_CHECKING:
    from .agent_loop import AgentLoop


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tool_call(value: Any) -> ToolCall | None:
    if isinstance(value, ToolCall):
        return value
    item = _as_record(value)
    name = str(item.get("name", "")).strip()
    if not name:
        return None
    return ToolCall(
        id=str(item.get("id", "")),
        name=name,
        arguments=_as_record(item.get("arguments")),
    )


def _metadata(reasoning: str, thinking_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    if not reasoning and not thinking_blocks:
        return {}
    blocks = thinking_blocks or ([{"type": "thinking", "thinking": reasoning}] if reasoning else [])
    text = reasoning or "".join(str(block.get("thinking", "")) for block in thinking_blocks)
    metadata: dict[str, Any] = {}
    if text:
        metadata["reasoning_content"] = text
        metadata["thinking"] = text
    if blocks:
        metadata["thinking_blocks"] = blocks
    return metadata


async def complete_with_stream(loop: AgentLoop, request: LLMRequest) -> LLMResponse:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    thinking_blocks: list[dict[str, Any]] = []
    tool_calls: list[ToolCall] = []
    usage_acc = LLMUsage().model_dump()
    saw_chunk = False

    async for chunk in loop._adapter.stream(request):
        saw_chunk = True
        if chunk.type == "text":
            text = str(chunk.data or "")
            if text:
                content_parts.append(text)
                loop._emit("text_delta", text)
        elif chunk.type == "reasoning":
            if isinstance(chunk.data, dict):
                thinking_blocks.append(chunk.data)
                continue
            text = str(chunk.data or "")
            if text:
                reasoning_parts.append(text)
                loop._emit("reasoning_delta", text)
        elif chunk.type == "tool_call":
            call = _tool_call(chunk.data)
            if call is not None:
                tool_calls.append(call)
        elif chunk.type == "usage":
            merge_usage(usage_acc, chunk.data)

    if not saw_chunk:
        return await loop._adapter.complete(request)

    reasoning = "".join(reasoning_parts)
    return LLMResponse(
        content="".join(content_parts),
        tool_calls=tool_calls,
        usage=LLMUsage(**usage_acc),
        provider_metadata=_metadata(reasoning, thinking_blocks),
    )


__all__ = ["complete_with_stream"]
