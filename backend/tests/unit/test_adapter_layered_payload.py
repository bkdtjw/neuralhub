from __future__ import annotations

import json

from backend.adapters.anthropic_support import build_payload as build_anthropic_payload
from backend.adapters.anthropic_support import parse_response as parse_anthropic_response
from backend.adapters.openai_support import build_payload as build_openai_payload
from backend.common.types import LLMRequest, Message, ToolDefinition, ToolParameterSchema


def _tool(name: str = "search_products") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Search products",
        category="search",
        parameters=ToolParameterSchema(properties={"query": {"type": "string"}}),
    )


def test_anthropic_payload_uses_top_level_system_cache_control() -> None:
    request = LLMRequest(
        model="claude",
        system_prompt="stable system",
        tools=[_tool()],
        messages=[
            Message(role="system", content="stable system"),
            Message(role="user", content="legacy user"),
        ],
        recent_messages=[Message(role="user", content="zone user")],
    )

    payload = build_anthropic_payload(request, "claude", stream=False)

    assert payload["system"][0]["text"] == "stable system"
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert payload["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "zone user"}]}
    ]


def test_anthropic_prefix_bytes_stay_stable_across_recent_messages() -> None:
    first = LLMRequest(
        model="claude",
        system_prompt="stable",
        tools=[_tool()],
        recent_messages=[Message(role="user", content="first")],
    )
    second = first.model_copy(
        update={"recent_messages": [Message(role="user", content="second")]}
    )

    first_payload = build_anthropic_payload(first, "claude", stream=False)
    second_payload = build_anthropic_payload(second, "claude", stream=False)

    assert json.dumps(first_payload["system"], sort_keys=True) == json.dumps(
        second_payload["system"], sort_keys=True
    )
    assert json.dumps(first_payload["tools"], sort_keys=True) == json.dumps(
        second_payload["tools"], sort_keys=True
    )


def test_openai_payload_orders_layered_messages_with_system_first() -> None:
    request = LLMRequest(
        model="gpt",
        system_prompt="stable",
        skill_messages=[Message(role="system", content="skill")],
        memory_messages=[Message(role="system", content="memory")],
        summary_message=Message(role="user", content="[对话历史摘要]\nsummary"),
        recent_messages=[Message(role="user", content="latest")],
    )

    payload = build_openai_payload(request, "gpt", stream=False)

    assert payload["messages"] == [
        {"role": "system", "content": "stable"},
        {"role": "system", "content": "skill"},
        {"role": "system", "content": "memory"},
        {"role": "user", "content": "[对话历史摘要]\nsummary"},
        {"role": "user", "content": "latest"},
    ]


def test_anthropic_parse_response_records_cache_read_tokens() -> None:
    response = parse_anthropic_response(
        {
            "id": "msg",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 5,
                "cache_read_input_tokens": 80,
            },
        }
    )

    assert response.usage.cached_prompt_tokens == 80
