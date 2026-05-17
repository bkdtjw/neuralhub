from __future__ import annotations

from typing import Any

from backend.common.types import ToolDefinition, ToolParameterSchema

from .models import ActionKind, BrowserAction


def tool_call_to_action(name: str, args: dict[str, Any]) -> BrowserAction:
    if name == ActionKind.DONE.value:
        return BrowserAction(kind=ActionKind.DONE, value=str(args.get("content", "")))
    if name == ActionKind.FAIL.value:
        return BrowserAction(kind=ActionKind.FAIL, reason=str(args.get("reason", "")))
    return BrowserAction(kind=ActionKind(name), **args)


def _tool(name: str, properties: dict[str, Any], required: list[str]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Browser action: {name}",
        category="browser",
        parameters=ToolParameterSchema(properties=properties, required=required),
    )


BROWSER_ACTION_TOOLS = [
    _tool("click_selector", {"selector": {"type": "string"}}, ["selector"]),
    _tool("click_coords", {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
    _tool(
        "fill",
        {"selector": {"type": "string"}, "value": {"type": "string"}},
        ["selector", "value"],
    ),
    _tool(
        "scroll",
        {"direction": {"type": "string"}, "amount": {"type": "integer"}},
        ["direction"],
    ),
    _tool("wait", {"amount": {"type": "integer"}}, ["amount"]),
    _tool("wait_for_selector", {"selector": {"type": "string"}}, ["selector"]),
    _tool("goto", {"url": {"type": "string"}}, ["url"]),
    _tool("key", {"value": {"type": "string"}}, ["value"]),
    _tool("extract_text", {"selector": {"type": "string"}}, []),
    _tool("screenshot", {"reason": {"type": "string"}}, []),
    _tool("done", {"content": {"type": "string"}}, ["content"]),
    _tool("fail", {"reason": {"type": "string"}}, ["reason"]),
]


__all__ = ["BROWSER_ACTION_TOOLS", "tool_call_to_action"]
