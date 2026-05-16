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
async def test_feishu_agent_loop_uses_public_product_tools_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock())

    tool_names = {definition.name for definition in loop._executor.list_definitions()}  # noqa: SLF001
    assert "product_search" in tool_names
    assert "product_coupon_lookup" in tool_names
    assert "jd_union_search" not in tool_names
    assert "zhetaoke_product_detail" not in tool_names
    assert "zhetaoke_taobao_search" not in tool_names
    assert "zhetaoke_brand_products" not in tool_names


@pytest.mark.asyncio
async def test_feishu_agent_loop_adds_browse_web_prompt_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock(), system_prompt="base")

    assert "browse_web" in loop._config.system_prompt  # noqa: SLF001
    assert "base" in loop._config.system_prompt  # noqa: SLF001


@pytest.mark.asyncio
async def test_feishu_agent_loop_adds_product_coupon_prompt_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock(), system_prompt="base")

    assert "product_coupon_lookup" in loop._config.system_prompt  # noqa: SLF001
    assert "不要为了查商品优惠券先打开浏览器" in loop._config.system_prompt  # noqa: SLF001


@pytest.mark.asyncio
async def test_feishu_agent_loop_skips_hint_when_tool_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())
    monkeypatch.setattr(feishu_runtime, "register_builtin_tools", lambda *args, **kwargs: None)

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock(), system_prompt="base")

    assert "browse_web" not in loop._config.system_prompt  # noqa: SLF001
    assert "product_coupon_lookup" not in loop._config.system_prompt  # noqa: SLF001


def test_base_system_prompt_does_not_include_browse_web_hint() -> None:
    assert "browse_web" not in build_system_prompt("/tmp")
    assert "product_coupon_lookup" not in build_system_prompt("/tmp")
