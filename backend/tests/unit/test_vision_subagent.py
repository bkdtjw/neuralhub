from __future__ import annotations

from backend.common.types import LLMResponse, ProviderConfig, ProviderType, ToolCall
from backend.core.s02_tools.builtin.browser_agent.vision_subagent import (
    VisionRequest,
    observe,
)


class FakeAdapter:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.request = None

    async def complete(self, request):
        self.request = request
        return self.response


class FakeRoleRouter:
    def __init__(self, adapter: FakeAdapter) -> None:
        self.adapter = adapter

    async def resolve_provider(self, role: str, override_id: str = "") -> ProviderConfig:
        self.role = role
        self.override_id = override_id
        return ProviderConfig(
            id="vision-provider",
            name="Vision",
            provider_type=ProviderType.OPENAI_COMPAT,
            base_url="https://example.com",
            default_model="vision-model",
        )

    async def get_adapter(self, provider_id: str) -> FakeAdapter:
        self.provider_id = provider_id
        return self.adapter


async def test_observe_parses_tool_call() -> None:
    adapter = FakeAdapter(
        LLMResponse(
            content="raw",
            tool_calls=[
                ToolCall(
                    name="report_observation",
                    arguments={
                        "page_summary": "Home page",
                        "visible_elements": [{"description": "Search box", "confidence": 0.8}],
                        "confidence": 0.9,
                    },
                )
            ],
        )
    )

    result = await observe(
        VisionRequest(screenshot=b"png", url="https://example.com", task_hint="find search"),
        FakeRoleRouter(adapter),
        provider_id="override",
    )

    assert result.page_summary == "Home page"
    assert result.visible_elements[0].description == "Search box"
    assert result.raw_text == "raw"
    assert adapter.request.tool_choice == {
        "type": "function",
        "function": {"name": "report_observation"},
    }
    assert adapter.request.messages[1].content[0]["type"] == "image_url"


async def test_observe_returns_need_human_on_parse_failure() -> None:
    adapter = FakeAdapter(LLMResponse(content="plain text"))

    result = await observe(
        VisionRequest(screenshot=b"png", url="https://example.com"),
        FakeRoleRouter(adapter),
    )

    assert result.need_human is True
    assert result.confidence == 0.0
    assert result.raw_text == "plain text"


async def test_observe_normalizes_json_string_target_element() -> None:
    adapter = FakeAdapter(
        LLMResponse(
            content="raw",
            tool_calls=[
                ToolCall(
                    name="report_observation",
                    arguments={
                        "page_summary": "Home page",
                        "target_element": '{"description": "Learn more", "confidence": 0.9}',
                    },
                )
            ],
        )
    )

    result = await observe(
        VisionRequest(screenshot=b"png", url="https://example.com"),
        FakeRoleRouter(adapter),
    )

    assert result.target_element is not None
    assert result.target_element.description == "Learn more"
