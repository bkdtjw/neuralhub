from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.api.routes import feishu_runtime
from backend.common.types import ToolDefinition, ToolParameterSchema, ToolResult
from backend.core.s06_context_compression import LongTermMemory, MemoryEntry
from backend.core.system_prompt import build_system_prompt


def _fake_tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        category="code-analysis",
        parameters=ToolParameterSchema(),
        side_effect=False,
    )


async def _fake_execute(_: dict[str, Any]) -> ToolResult:
    return ToolResult(output="ok")


@pytest.mark.asyncio
async def test_feishu_agent_loop_has_browse_web_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock())

    tool_names = {definition.name for definition in loop._executor.list_definitions()}  # noqa: SLF001
    assert "browse_web" in tool_names


@pytest.mark.asyncio
async def test_feishu_agent_loop_loads_memory_index(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMemoryStore:
        def load(self) -> LongTermMemory:
            return LongTermMemory(
                entries=[
                    MemoryEntry(
                        id="m1",
                        trigger="字幕附件",
                        lesson="已发送过字幕附件",
                        keywords=["字幕"],
                        source_session="oc_1",
                        created_at=datetime.utcnow(),
                    )
                ]
            )

    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())
    monkeypatch.setattr(feishu_runtime, "MemoryStore", FakeMemoryStore)

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock())

    assert loop._memory_index is not None  # noqa: SLF001
    assert loop._memory_index.match("字幕", limit=1)[0].lesson == "已发送过字幕附件"  # noqa: SLF001


@pytest.mark.asyncio
async def test_feishu_agent_loop_degrades_when_memory_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenMemoryStore:
        def load(self) -> LongTermMemory:
            raise RuntimeError("memory file is invalid")

    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())
    monkeypatch.setattr(feishu_runtime, "MemoryStore", BrokenMemoryStore)

    loop = await feishu_runtime.build_agent_loop(adapter=AsyncMock())

    assert loop._memory_index is None  # noqa: SLF001


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
    prompt = build_system_prompt()

    assert "你可以调用 browse_web 工具来自动完成多步骤的网页任务" not in prompt
    assert "调用方式：browse_web" not in prompt
    assert "product_coupon_lookup" not in prompt


@pytest.mark.asyncio
async def test_feishu_multi_agent_uses_queue_spawn_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_register(registry, *args, **kwargs):
        captured.update(kwargs)
        for name in ("dispatch_agent", "orchestrate_agents", "spawn_agent"):
            registry.register(_fake_tool(name), _fake_execute)

    monkeypatch.setattr(feishu_runtime.MCPToolBridge, "sync_all", AsyncMock())
    monkeypatch.setattr(feishu_runtime, "register_builtin_tools", fake_register)

    loop = await feishu_runtime.build_agent_loop(
        adapter=AsyncMock(),
        spec_registry=object(),
        task_queue=object(),
        system_prompt="base",
    )

    policy = captured["sub_agent_policy"]
    tool_names = {definition.name for definition in loop._executor.list_definitions()}  # noqa: SLF001
    assert "spawn_agent" in tool_names
    assert "dispatch_agent" not in tool_names
    assert "orchestrate_agents" not in tool_names
    assert "runtime-architect" in policy.allowed_specs
    assert "tech-research" in policy.allowed_specs
    assert "架构 reviewer" in policy.allowed_specs
    assert "安全工程师" in policy.allowed_specs
    assert policy.allow_inline_roles is True
    assert "research-specialist" in policy.allowed_inline_templates
    assert policy.max_iterations_cap == 40
    assert policy.max_concurrent == feishu_runtime.app_settings.sub_worker_max_concurrency
    assert "只能使用 spawn_agent" in loop._config.system_prompt  # noqa: SLF001
    assert "template + role + input" in loop._config.system_prompt  # noqa: SLF001
    assert "max_iterations 是单个子任务预算" in loop._config.system_prompt  # noqa: SLF001
    assert "不要再读取无关文件或执行无关 shell 命令" in loop._config.system_prompt  # noqa: SLF001
    assert "dispatch_agent 或 orchestrate_agents" in loop._config.system_prompt  # noqa: SLF001
