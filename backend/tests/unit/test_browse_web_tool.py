from __future__ import annotations

from pathlib import Path
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


async def test_browse_web_tool_applies_jd_site_guide(monkeypatch: pytest.MonkeyPatch) -> None:
    run_mock = AsyncMock(return_value=BrowserAgentResult(success=True, content="answer"))
    monkeypatch.setattr(browse_tool, "run_browser_agent", run_mock)
    _, execute = browse_tool.create_browse_web_tool(object())

    result = await execute({"task": "用浏览器打开 https://www.jd.com/ 查看京东"})

    config = run_mock.await_args.args[0]
    assert result.is_error is False
    assert config.domain == "jd.com"
    assert config.initial_url == "https://www.jd.com?from=pc_search_sd"
    assert "corporate.jd.com" in config.site_guide


async def test_browse_web_tool_attaches_core_screenshot_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_shot = tmp_path / "old.png"
    final_shot = tmp_path / "final.png"
    old_shot.write_bytes(b"old")
    final_shot.write_bytes(b"final")
    run_mock = AsyncMock(
        return_value=BrowserAgentResult(
            success=True,
            content="answer",
            screenshots=[old_shot, final_shot],
        )
    )
    monkeypatch.setattr(browse_tool, "run_browser_agent", run_mock)
    _, execute = browse_tool.create_browse_web_tool(object())

    result = await execute({"task": "find info"})

    assert result.artifacts[0].source == "browse_web"
    assert result.artifacts[0].path == str(final_shot)
    assert old_shot.exists() is False
    assert final_shot.exists() is True
    assert run_mock.await_args.args[2].root.exists() is False


async def test_browse_web_tool_returns_human_gate_as_non_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shot = tmp_path / "qr.png"
    shot.write_bytes(b"qr")
    run_mock = AsyncMock(
        return_value=BrowserAgentResult(
            success=False,
            reason="need_human",
            content="需要人工处理后继续：需要扫码登录。",
            screenshots=[shot],
        )
    )
    monkeypatch.setattr(browse_tool, "run_browser_agent", run_mock)
    _, execute = browse_tool.create_browse_web_tool(object())

    result = await execute({"task": "login required"})

    assert result.is_error is False
    assert "需要扫码登录" in result.output
    assert result.artifacts[0].label == "browse_web_human_required"
    assert result.artifacts[0].path == str(shot)


def test_builtin_tools_registers_browse_web() -> None:
    registry = ToolRegistry()

    register_builtin_tools(registry, workspace=None)

    assert registry.has("browse_web")
