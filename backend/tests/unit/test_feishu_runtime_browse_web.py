from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.api.routes import feishu_runtime
from backend.core.system_prompt import build_system_prompt


@pytest.mark.asyncio
async def test_feishu_agent_loop_has_browse_web_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock())

    tool_names = {definition.name for definition in loop._executor.list_definitions()}  # noqa: SLF001
    assert "browse_web" in tool_names


@pytest.mark.asyncio
async def test_feishu_agent_loop_adds_browse_web_prompt_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock(), system_prompt="base")

    assert "browse_web" in loop._config.system_prompt  # noqa: SLF001
    assert "base" in loop._config.system_prompt  # noqa: SLF001
    assert "storage_state/cookie 文件存在不等于已经登录" in loop._config.system_prompt  # noqa: SLF001


@pytest.mark.asyncio
async def test_feishu_agent_loop_skips_hint_when_tool_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())
    monkeypatch.setattr(feishu_runtime, "register_builtin_tools", lambda *args, **kwargs: None)

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock(), system_prompt="base")

    assert "browse_web" not in loop._config.system_prompt  # noqa: SLF001


def test_base_system_prompt_does_not_include_browse_web_hint() -> None:
    assert "browse_web" not in build_system_prompt("/tmp")
