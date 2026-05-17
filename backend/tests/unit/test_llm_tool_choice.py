from __future__ import annotations

from backend.adapters.anthropic_support import build_payload as build_anthropic_payload
from backend.adapters.openai_support import build_payload as build_openai_payload
from backend.common.types import LLMRequest, Message, ToolDefinition, ToolParameterSchema


def _request(tool_choice: str | dict[str, object]) -> LLMRequest:
    return LLMRequest(
        model="model",
        messages=[Message(role="user", content="hi")],
        tools=[
            ToolDefinition(
                name="report_observation",
                description="Report observation",
                category="browser",
                parameters=ToolParameterSchema(properties={}, required=[]),
            )
        ],
        tool_choice=tool_choice,
    )


def test_openai_payload_maps_any_tool_choice_to_required() -> None:
    payload = build_openai_payload(_request("any"), "model", stream=False)

    assert payload["tool_choice"] == "required"


def test_openai_payload_preserves_function_tool_choice() -> None:
    choice = {"type": "function", "function": {"name": "report_observation"}}
    payload = build_openai_payload(_request(choice), "model", stream=False)

    assert payload["tool_choice"] == choice


def test_anthropic_payload_maps_any_tool_choice() -> None:
    payload = build_anthropic_payload(_request("any"), "model", stream=False)

    assert payload["tool_choice"] == {"type": "any"}


def test_anthropic_payload_maps_function_tool_choice() -> None:
    choice = {"type": "function", "function": {"name": "report_observation"}}
    payload = build_anthropic_payload(_request(choice), "model", stream=False)

    assert payload["tool_choice"] == {"type": "tool", "name": "report_observation"}
