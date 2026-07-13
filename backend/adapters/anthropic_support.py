from __future__ import annotations

from typing import Any

from backend.common import LLMError
from backend.common.types import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    Message,
    ToolCall,
    ToolDefinition,
)

from .anthropic_stream import parse_stream_line
from .message_zones import request_system_prompt, request_zone_messages


def build_payload(request: LLMRequest, default_model: str, *, stream: bool) -> dict[str, Any]:
    system_prompt = request_system_prompt(request)
    payload: dict[str, Any] = {
        "model": request.model or default_model,
        "messages": to_anthropic_messages_v2(request),
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    if system_prompt:
        payload["system"] = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    if request.tools:
        tools = to_anthropic_tools(request.tools)
        tools[-1]["cache_control"] = {"type": "ephemeral"}
        payload["tools"] = tools
    if request.tool_choice is not None:
        payload["tool_choice"] = _to_anthropic_tool_choice(request.tool_choice)
    if request.thinking:
        budget_tokens = max(1024, min(4096, request.max_tokens - 1))
        if payload["max_tokens"] <= budget_tokens:
            payload["max_tokens"] = budget_tokens + 1
        payload["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
        payload["temperature"] = 1.0
    if stream:
        payload["stream"] = True
    return payload


def to_anthropic_messages_v2(request: LLMRequest) -> list[dict[str, Any]]:
    return to_anthropic_messages(request_zone_messages(request, include_system=False))


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "assistant":
            result.append(_assistant_message(msg))
            continue
        if msg.role == "tool" and msg.tool_results:
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": res.tool_call_id,
                    "content": res.output,
                    "is_error": res.is_error,
                }
                for res in msg.tool_results
            ]
            result.append({"role": "user", "content": content})
            continue
        if msg.role == "system":
            continue
        result.append({"role": "user", "content": [{"type": "text", "text": msg.content}]})
    return result


def _assistant_message(msg: Message) -> dict[str, Any]:
    thinking_blocks = msg.provider_metadata.get("thinking_blocks", [])
    content = [
        block
        for block in thinking_blocks
        if isinstance(block, dict)
    ]
    if msg.content:
        content.append({"type": "text", "text": msg.content})
    for call in msg.tool_calls or []:
        content.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
        )
    return {"role": "assistant", "content": content or [{"type": "text", "text": ""}]}


def to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters.model_dump(),
        }
        for tool in tools
    ]


def _to_anthropic_tool_choice(choice: str | dict[str, Any]) -> str | dict[str, Any]:
    if isinstance(choice, str):
        return {"type": "any"} if choice in {"any", "required"} else {"type": choice}
    if choice.get("type") == "function":
        name = choice.get("function", {}).get("name", "")
        if name:
            return {"type": "tool", "name": name}
    return choice


def parse_response(data: dict[str, Any]) -> LLMResponse:
    if data.get("success") is False:
        raise LLMError("API_ERROR", str(data.get("msg") or data), "anthropic", None)
    content_blocks = data.get("content", [])
    content = "".join(
        block.get("text", "") for block in content_blocks if block.get("type") == "text"
    )
    tool_calls = [
        ToolCall(
            id=block.get("id", ""),
            name=block.get("name", ""),
            arguments=block.get("input", {}),
        )
        for block in content_blocks
        if block.get("type") == "tool_use"
    ]
    usage = data.get("usage", {})
    provider_metadata = _provider_metadata(content_blocks)
    return LLMResponse(
        id=data.get("id", ""),
        content=content,
        tool_calls=tool_calls,
        usage=LLMUsage(
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            cached_prompt_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_prompt_tokens=usage.get("cache_creation_input_tokens", 0),
        ),
        provider_metadata=provider_metadata,
    )


def _provider_metadata(content_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    thinking_blocks = [block for block in content_blocks if block.get("type") == "thinking"]
    if not thinking_blocks:
        return {}
    return {
        "thinking_blocks": thinking_blocks,
        "thinking": "".join(str(block.get("thinking", "")) for block in thinking_blocks),
    }


def build_headers(api_key: str, extra_headers: dict[str, str]) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        **extra_headers,
    }
