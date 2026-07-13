from __future__ import annotations

from backend.api.routes.completion_runtime import (
    RuntimeRegistryKey,
    get_runtime_registry,
    reset_runtime_registry_cache,
)
from backend.common.types import ToolDefinition, ToolParameterSchema, ToolResult
from backend.core.s02_tools import ToolRegistry


class _FakeServerManager:
    """最小 MCP manager 替身：记录 list_servers 调用次数。"""

    def __init__(self) -> None:
        self.version = 0
        self.list_calls = 0

    async def list_servers(self) -> list:
        self.list_calls += 1
        return []


def _key(model: str = "m", workspace: str = "/ws") -> RuntimeRegistryKey:
    return RuntimeRegistryKey(workspace=workspace, mode="auto", model=model, provider_id="p")


def _register_demo_tool(registry: ToolRegistry) -> None:
    definition = ToolDefinition(
        name="demo",
        description="demo tool",
        category="shell",
        parameters=ToolParameterSchema(properties={}),
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        return ToolResult(output="ok")

    registry.register(definition, execute)


async def test_same_key_reuses_registry_instance() -> None:
    reset_runtime_registry_cache()
    manager = _FakeServerManager()
    builds = 0

    def build(registry: ToolRegistry) -> None:
        nonlocal builds
        builds += 1
        _register_demo_tool(registry)

    first = await get_runtime_registry(_key(), manager, build)
    second = await get_runtime_registry(_key(), manager, build)

    assert first.registry is second.registry
    assert first.bridge is second.bridge
    assert builds == 1


async def test_different_key_builds_separate_registry() -> None:
    reset_runtime_registry_cache()
    manager = _FakeServerManager()

    first = await get_runtime_registry(_key(model="a"), manager, _register_demo_tool)
    second = await get_runtime_registry(_key(model="b"), manager, _register_demo_tool)

    assert first.registry is not second.registry


async def test_mcp_sync_runs_once_until_version_changes() -> None:
    reset_runtime_registry_cache()
    manager = _FakeServerManager()

    await get_runtime_registry(_key(), manager, _register_demo_tool)
    await get_runtime_registry(_key(), manager, _register_demo_tool)
    assert manager.list_calls == 1

    manager.version = 1
    await get_runtime_registry(_key(), manager, _register_demo_tool)
    assert manager.list_calls == 2


async def test_cache_evicts_oldest_beyond_capacity() -> None:
    reset_runtime_registry_cache()
    manager = _FakeServerManager()

    first = await get_runtime_registry(_key(model="m0"), manager, _register_demo_tool)
    for i in range(1, 9):
        await get_runtime_registry(_key(model=f"m{i}"), manager, _register_demo_tool)

    rebuilt = await get_runtime_registry(_key(model="m0"), manager, _register_demo_tool)
    assert rebuilt.registry is not first.registry
