from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.core.s02_tools.builtin.browser_agent import tool as browse_tool
from backend.core.s02_tools.builtin.browser_agent.models import BrowserAgentResult


def test_browse_web_tool_definition_schema() -> None:
    definition, _ = browse_tool.create_browse_web_tool(object())

    assert definition.name == "browse_web"
    assert definition.category == "browser"
    assert definition.parameters.required == ["task"]
    assert "vision_provider_id" in definition.parameters.properties


async def test_browse_web_tool_execute_returns_success(monkeypatch: pytest.MonkeyPatch) -> None:
    run_mock = AsyncMock(
        return_value=BrowserAgentResult(success=True, content="answer", steps_taken=3)
    )
    monkeypatch.setattr(browse_tool, "run_browser_agent", run_mock)
    _, execute = browse_tool.create_browse_web_tool(object())

    result = await execute({"task": "find info", "max_steps": 99})

    assert result.is_error is False
    assert result.output == "answer"
    config = run_mock.await_args.args[0]
    assert config.max_steps == 30


def test_builtin_tools_registers_browse_web() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("browse_web")
