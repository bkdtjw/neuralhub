from __future__ import annotations

import json
from typing import Any, Literal

from backend.common.types import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

from .message_zones import request_zone_messages
from .openai_thinking import apply_thinking_payload
from .openai_usage import usage_stream_chunk


def build_payload(
    request: LLMRequest,
    default_model: str,
    *,
    stream: bool,
    extra_body: dict[str, Any] | None = None,
    enable_prompt_cache: bool = False,
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None,
    include_usage: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model or default_model,
        "messages": to_openai_messages(request_zone_messages(request, include_system=True)),
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if request.tools:
        payload["tools"] = to_openai_tools(request.tools)
    if request.tool_choice is not None:
        payload["tool_choice"] = "required" if request.tool_choice == "any" else request.tool_choice
    if stream:
        payload["stream"] = True
        # Opt-in only: many third-party gateways 400 on stream_options, so the
        # adapter enables this per-provider rather than unconditionally.
        if include_usage:
            payload["stream_options"] = {"include_usage": True}
    if extra_body:
        payload.update(extra_body)
    apply_thinking_payload(payload, request)
    if enable_prompt_cache:
        if request.prompt_cache_key:
            payload["prompt_cache_key"] = request.prompt_cache_key
        retention = request.prompt_cache_retention or prompt_cache_retention
        if retention:
            payload["prompt_cache_retention"] = retention
    return payload


def to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "assistant":
            result.append(_assistant_message(msg))
            continue
        if msg.role == "tool" and msg.tool_results:
            for res in msg.tool_results:
                result.append({"role": "tool", "tool_call_id": res.tool_call_id, "content": res.output})
            continue
        role = msg.role if msg.role in {"system", "user"} else "user"
        result.append({"role": role, "content": msg.content})
    return result


def _assistant_message(msg: Message) -> dict[str, Any]:
    content = None if msg.tool_calls and not msg.content else msg.content
    item: dict[str, Any] = {"role": "assistant", "content": content}
    reasoning = msg.provider_metadata.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        item["reasoning_content"] = reasoning
    if msg.tool_calls:
        item["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in msg.tool_calls
        ]
    return item


def to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters.model_dump(),
            },
        }
        for tool in tools
    ]


def parse_response(data: dict[str, Any]) -> LLMResponse:
    message = (data.get("choices") or [{}])[0].get("message", {})
    tool_calls = [
        ToolCall(
            id=tool_call.get("id", ""),
            name=tool_call.get("function", {}).get("name", ""),
            arguments=parse_args(tool_call.get("function", {}).get("arguments", "")),
        )
        for tool_call in message.get("tool_calls", []) or []
    ]
    usage = data.get("usage", {})
    provider_metadata = _provider_metadata(message)
    details = usage.get("prompt_tokens_details", {})
    cached_tokens = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    return LLMResponse(
        id=data.get("id", ""),
        content=message.get("content", "") or "",
        tool_calls=tool_calls,
        usage=LLMUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cached_prompt_tokens=cached_tokens,
        ),
        provider_metadata=provider_metadata,
    )


def _provider_metadata(message: dict[str, Any]) -> dict[str, Any]:
    reasoning = message.get("reasoning_content")
    return {"reasoning_content": reasoning} if isinstance(reasoning, str) and reasoning else {}


def parse_stream_line(raw: str, tool_chunks: dict[int, dict[str, str]]) -> list[StreamChunk]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    choice = (data.get("choices") or [{}])[0]
    delta = choice.get("delta", {})
    for tool_call in delta.get("tool_calls", []) or []:
        index = tool_call.get("index", 0)
        buffer = tool_chunks.setdefault(index, {"id": "", "name": "", "arguments": ""})
        buffer["id"] = tool_call.get("id", buffer["id"])
        function = tool_call.get("function", {})
        buffer["name"] = function.get("name", buffer["name"])
        arguments = function.get("arguments", "")
        if isinstance(arguments, dict):
            buffer["arguments"] += json.dumps(arguments, ensure_ascii=False)
        elif arguments is not None:
            buffer["arguments"] += str(arguments)
    chunks = [
        StreamChunk(type=chunk_type, data=delta[key])
        for chunk_type, key in (("reasoning", "reasoning_content"), ("text", "content"))
        if delta.get(key)
    ]
    usage = usage_stream_chunk(data)
    if usage is not None:
        chunks.append(usage)
    if choice.get("finish_reason") == "tool_calls":
        chunks.extend(flush_tool_calls(tool_chunks))
    return chunks


def flush_tool_calls(tool_chunks: dict[int, dict[str, str]]) -> list[StreamChunk]:
    chunks = [
        StreamChunk(
            type="tool_call",
            data={
                "id": value["id"],
                "name": value["name"],
                "arguments": parse_args(value["arguments"]),
            },
        )
        for _, value in sorted(tool_chunks.items())
        if value["name"]
    ]
    tool_chunks.clear()
    return chunks


def parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw}


def build_headers(api_key: str, extra_headers: dict[str, str]) -> dict[str, str]:
    auth_header = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return {"content-type": "application/json", **extra_headers, **auth_header}
