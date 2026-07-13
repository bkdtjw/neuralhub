from __future__ import annotations

import json

from backend.adapters.anthropic_support import build_payload as build_anthropic_payload
from backend.adapters.anthropic_support import parse_response as parse_anthropic_response
from backend.adapters.anthropic_support import parse_stream_line as parse_anthropic_stream_line
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
        skill_messages=[Message(role="user", kind="skill_context", content="<skill_context>\nskill\n</skill_context>")],
        memory_messages=[Message(role="user", kind="memory_context", content="<memory_context>\nmemory\n</memory_context>")],
        runtime_messages=[Message(role="user", kind="runtime_context", content="<runtime_context>\nworkspace\n</runtime_context>")],
        summary_message=Message(role="user", kind="summary", content="<conversation_summary>\nsummary\n</conversation_summary>"),
        recent_messages=[Message(role="user", content="latest")],
    )

    payload = build_openai_payload(request, "gpt", stream=False)

    assert payload["messages"] == [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "<skill_context>\nskill\n</skill_context>"},
        {"role": "user", "content": "<memory_context>\nmemory\n</memory_context>"},
        {"role": "user", "content": "<runtime_context>\nworkspace\n</runtime_context>"},
        {"role": "user", "content": "<conversation_summary>\nsummary\n</conversation_summary>"},
        {"role": "user", "content": "latest"},
    ]


def test_anthropic_payload_keeps_skill_memory_user_context() -> None:
    request = LLMRequest(
        model="claude",
        system_prompt="stable",
        skill_messages=[Message(role="user", kind="skill_context", content="<skill_context>\nskill\n</skill_context>")],
        memory_messages=[Message(role="user", kind="memory_context", content="<memory_context>\nmemory\n</memory_context>")],
        recent_messages=[Message(role="user", content="latest")],
    )

    payload = build_anthropic_payload(request, "claude", stream=False)
    texts = [item["content"][0]["text"] for item in payload["messages"]]

    assert "<skill_context>" in texts[0]
    assert "<memory_context>" in texts[1]
    assert texts[-1] == "latest"


def test_anthropic_parse_response_records_cache_read_tokens() -> None:
    response = parse_anthropic_response(
        {
            "id": "msg",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 5,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 30,
            },
        }
    )

    assert response.usage.cached_prompt_tokens == 80
    assert response.usage.cache_creation_prompt_tokens == 30
    # Anthropic 的 input_tokens 天然不含 cache_read/cache_creation，不做扣减。
    assert response.usage.prompt_tokens == 100


def test_anthropic_stream_parser_buffers_tool_input_json_delta() -> None:
    tool_blocks: dict[int, dict[str, object]] = {}
    start = {
        "index": 0,
        "content_block": {"type": "tool_use", "id": "tool-1", "name": "zhetaoke_taobao_search", "input": {}},
    }
    first = {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"q":"露营灯",'}}
    second = {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '"page_size":5}'}}

    assert parse_anthropic_stream_line("content_block_start", json.dumps(start), "anthropic", tool_blocks) is None
    assert parse_anthropic_stream_line("content_block_delta", json.dumps(first), "anthropic", tool_blocks) is None
    assert parse_anthropic_stream_line("content_block_delta", json.dumps(second), "anthropic", tool_blocks) is None
    chunk = parse_anthropic_stream_line("content_block_stop", json.dumps({"index": 0}), "anthropic", tool_blocks)

    assert chunk is not None
    assert chunk.type == "tool_call"
    assert chunk.data["arguments"] == {"q": "露营灯", "page_size": 5}
