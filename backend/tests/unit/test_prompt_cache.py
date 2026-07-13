from __future__ import annotations

from collections.abc import AsyncIterator
import json

import pytest

from backend.adapters.base import LLMAdapter
from backend.adapters.openai_support import build_payload, parse_response, parse_stream_line
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    Message,
    ProviderConfig,
    ProviderType,
    StreamChunk,
    ToolDefinition,
    ToolParameterSchema,
)
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s01_agent_loop.agent_loop_support import PromptCachePrefix, build_prompt_cache_key
from backend.core.s02_tools.registry import ToolRegistry
from backend.storage.provider_serializers import to_provider_config, to_provider_record


class CaptureAdapter(LLMAdapter):
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="done")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


def _tool(name: str = "Read") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} files",
        category="file-ops",
        parameters=ToolParameterSchema(
            properties={"path": {"type": "string"}},
            required=["path"],
        ),
    )


def test_openai_payload_adds_prompt_cache_fields_only_when_enabled() -> None:
    request = LLMRequest(
        model="gpt-5.1",
        messages=[Message(role="user", content="hi")],
        prompt_cache_key="agent-studio:test",
    )
    disabled = build_payload(request, "gpt-5.1", stream=False)
    enabled = build_payload(
        request,
        "gpt-5.1",
        stream=False,
        extra_body={"parallel_tool_calls": False},
        enable_prompt_cache=True,
        prompt_cache_retention="24h",
    )
    assert "prompt_cache_key" not in disabled
    assert enabled["prompt_cache_key"] == "agent-studio:test"
    assert enabled["prompt_cache_retention"] == "24h"
    assert enabled["parallel_tool_calls"] is False


def test_openai_parse_response_records_cached_prompt_tokens() -> None:
    response = parse_response(
        {
            "id": "resp-1",
            "choices": [{"message": {"content": "answer"}}],
            "usage": {
                "prompt_tokens": 2006,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 1920},
            },
        }
    )
    assert response.usage.cached_prompt_tokens == 1920
    # 未命中输入口径：OpenAI 的 prompt_tokens 含 cached_tokens，入账前扣除（2006-1920=86）。
    assert response.usage.prompt_tokens == 86


def test_openai_parse_response_preserves_object_tool_arguments() -> None:
    response = parse_response(
        {
            "id": "resp-1",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "product_coupon_lookup",
                                    "arguments": {"text": "https://item.taobao.com/item.htm?id=1"},
                                },
                            }
                        ]
                    }
                }
            ],
        }
    )

    assert response.tool_calls[0].arguments == {"text": "https://item.taobao.com/item.htm?id=1"}


def test_openai_stream_parser_preserves_object_tool_arguments() -> None:
    tool_chunks: dict[int, dict[str, str]] = {}
    payload = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-1",
                            "function": {
                                "name": "zhetaoke_product_detail",
                                "arguments": {"tao_id": "10025768652616"},
                            },
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    chunks = parse_stream_line(json.dumps(payload, ensure_ascii=False), tool_chunks)

    assert chunks[0].data["arguments"] == {"tao_id": "10025768652616"}


def test_prompt_cache_key_is_stable_for_same_prefix() -> None:
    first = build_prompt_cache_key(PromptCachePrefix("provider", "gpt-5.1", "system", [_tool()]))
    second = build_prompt_cache_key(PromptCachePrefix("provider", "gpt-5.1", "system", [_tool()]))
    changed = build_prompt_cache_key(
        PromptCachePrefix("provider", "gpt-5.1", "system", [_tool("Write")])
    )
    assert first == second
    assert first != changed


@pytest.mark.asyncio
async def test_agent_loop_attaches_prompt_cache_key_to_request() -> None:
    adapter = CaptureAdapter()
    loop = AgentLoop(
        AgentConfig(model="gpt-5.1", provider="openai-provider", system_prompt="system"),
        adapter,
        ToolRegistry(),
    )
    await loop.run("hello")
    assert adapter.requests[0].prompt_cache_key.startswith("agent-studio:openai-provider:gpt-5.1:")


def test_provider_prompt_cache_fields_roundtrip() -> None:
    config = ProviderConfig(
        name="OpenAI",
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="https://api.openai.com/v1",
        default_model="gpt-5.1",
        enable_prompt_cache=True,
        prompt_cache_retention="24h",
        extra_body={"parallel_tool_calls": False},
    )
    restored = to_provider_config(to_provider_record(config))
    assert restored.enable_prompt_cache is True
    assert restored.prompt_cache_retention == "24h"
    assert restored.extra_body == {"parallel_tool_calls": False}
