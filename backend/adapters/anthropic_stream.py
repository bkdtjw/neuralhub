from __future__ import annotations

import json
from typing import Any

from backend.common import LLMError
from backend.common.types import LLMResponse, LLMUsage, StreamChunk, merge_usage


def parse_stream_line(
    event_type: str,
    raw: str,
    provider: str,
    tool_blocks: dict[int, dict[str, Any]] | None = None,
    thinking_blocks: dict[int, dict[str, Any]] | None = None,
) -> StreamChunk | None:
    if raw == "[DONE]" or event_type == "message_stop":
        return StreamChunk(type="done")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if event_type == "content_block_delta":
        return _delta_chunk(data, tool_blocks, thinking_blocks)
    if event_type == "content_block_start":
        return _start_chunk(data, tool_blocks, thinking_blocks)
    if event_type == "content_block_stop":
        return _stop_chunk(data, tool_blocks, thinking_blocks)
    if event_type == "message_start":
        return _message_start_usage(data)
    if event_type == "message_delta":
        return _message_delta_usage(data)
    if event_type == "error":
        detail = data.get("error", {}).get("message", str(data))
        raise LLMError("STREAM_ERROR", detail, provider, None)
    return None


def _delta_chunk(
    data: dict[str, Any],
    tool_blocks: dict[int, dict[str, Any]] | None,
    thinking_blocks: dict[int, dict[str, Any]] | None,
) -> StreamChunk | None:
    delta = data.get("delta", {})
    delta_type = delta.get("type")
    index = int(data.get("index", 0))
    if delta_type == "input_json_delta" and tool_blocks is not None:
        block = tool_blocks.setdefault(index, {"id": "", "name": "", "input": {}, "json": ""})
        block["json"] = f"{block.get('json', '')}{delta.get('partial_json', '')}"
        return None
    if delta_type == "signature_delta" and thinking_blocks is not None:
        slot = _thinking_slot(thinking_blocks, index)
        slot["signature"] = f"{slot['signature']}{delta.get('signature', '')}"
        return None
    if delta_type == "thinking_delta" and delta.get("thinking"):
        if thinking_blocks is not None:
            slot = _thinking_slot(thinking_blocks, index)
            slot["thinking"] = f"{slot['thinking']}{delta['thinking']}"
        return StreamChunk(type="reasoning", data=delta["thinking"])
    if delta_type == "text_delta" and delta.get("text"):
        return StreamChunk(type="text", data=delta["text"])
    return None


def _start_chunk(
    data: dict[str, Any],
    tool_blocks: dict[int, dict[str, Any]] | None,
    thinking_blocks: dict[int, dict[str, Any]] | None,
) -> StreamChunk | None:
    block = data.get("content_block", {})
    block_type = block.get("type")
    if block_type == "thinking" and thinking_blocks is not None:
        slot = _thinking_slot(thinking_blocks, int(data.get("index", 0)))
        slot["thinking"] = f"{slot['thinking']}{block.get('thinking', '')}"
        slot["signature"] = f"{slot['signature']}{block.get('signature', '')}"
        return None
    if block_type != "tool_use":
        return None
    if tool_blocks is None:
        return _tool_chunk(block.get("id", ""), block.get("name", ""), _as_record(block.get("input")))
    tool_blocks[int(data.get("index", 0))] = {
        "id": block.get("id", ""),
        "name": block.get("name", ""),
        "input": _as_record(block.get("input")),
        "json": "",
    }
    return None


def _stop_chunk(
    data: dict[str, Any],
    tool_blocks: dict[int, dict[str, Any]] | None,
    thinking_blocks: dict[int, dict[str, Any]] | None,
) -> StreamChunk | None:
    index = int(data.get("index", 0))
    if thinking_blocks is not None and index in thinking_blocks:
        return StreamChunk(type="reasoning", data=thinking_blocks.pop(index))
    if tool_blocks is None:
        return None
    block = tool_blocks.pop(index, None)
    if block is None:
        return None
    arguments = _json_record(str(block.get("json", ""))) or _as_record(block.get("input"))
    return _tool_chunk(block.get("id", ""), block.get("name", ""), arguments)


def _message_start_usage(data: dict[str, Any]) -> StreamChunk | None:
    # message_start carries prompt/cached counts; its output_tokens is only the
    # initial (~1) value, so it is ignored here and taken from message_delta.
    message = data.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    return _usage_chunk(
        int(usage.get("input_tokens", 0) or 0),
        0,
        int(usage.get("cache_read_input_tokens", 0) or 0),
    )


def _message_delta_usage(data: dict[str, Any]) -> StreamChunk | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    # Kimi 的 anthropic 兼容层把扣除缓存后的真实 input/cache_read 放在 message_delta
    # （官方协议放 message_start，delta 不带这两个字段）。merge_usage 的最后非零覆盖
    # 语义天然兼容两种口径；此前只取 output 会把 Kimi 的缓存命中数整个丢掉。
    return _usage_chunk(
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
        int(usage.get("cache_read_input_tokens", 0) or 0),
    )


def _usage_chunk(prompt: int, completion: int, cached: int) -> StreamChunk:
    return StreamChunk(
        type="usage",
        data={
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_prompt_tokens": cached,
        },
    )


def new_usage_acc() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}


def fold_usage(acc: dict[str, int], chunk: StreamChunk) -> None:
    merge_usage(acc, chunk.data)


def stream_usage_response(acc: dict[str, int]) -> LLMResponse:
    return LLMResponse(content="", usage=LLMUsage(**acc))


def _thinking_slot(thinking_blocks: dict[int, dict[str, Any]], index: int) -> dict[str, Any]:
    return thinking_blocks.setdefault(index, {"type": "thinking", "thinking": "", "signature": ""})


def _tool_chunk(tool_id: Any, name: Any, arguments: dict[str, Any]) -> StreamChunk:
    return StreamChunk(
        type="tool_call",
        data={"id": str(tool_id), "name": str(name), "arguments": arguments},
    )


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_record(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return _as_record(value)


__all__ = ["parse_stream_line", "new_usage_acc", "fold_usage", "stream_usage_response"]
