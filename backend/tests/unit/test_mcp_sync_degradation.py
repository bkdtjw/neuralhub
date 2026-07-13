from __future__ import annotations

from pathlib import Path

import pytest

from backend.common.errors import AgentError
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.mcp import MCPToolBridge

from .mcp_test_support import BrokenDisconnectClient, make_flaky_manager, server_config


@pytest.mark.asyncio
async def test_sync_all_skips_failing_server(tmp_path: Path) -> None:
    manager, created = await make_flaky_manager(tmp_path)
    await manager.add_server(server_config("healthy"))
    await manager.add_server(server_config("flaky"))
    created["flaky"].fail_list_tools = True
    registry = ToolRegistry()

    assert await MCPToolBridge(manager, registry).sync_all() == 1

    assert registry.has("mcp__healthy__echo") is True
    assert registry.has("mcp__flaky__echo") is False
    statuses = {status.id: status for status in await manager.list_servers()}
    assert statuses["flaky"].connected is False
    assert statuses["flaky"].tool_count == 0
    assert statuses["healthy"].connected is True


@pytest.mark.asyncio
async def test_sync_servers_skips_failing_server(tmp_path: Path) -> None:
    manager, created = await make_flaky_manager(tmp_path)
    await manager.add_server(server_config("healthy"))
    await manager.add_server(server_config("flaky"))
    created["flaky"].fail_list_tools = True
    registry = ToolRegistry()

    assert await MCPToolBridge(manager, registry).sync_servers({"healthy", "flaky"}) == 1

    assert registry.has("mcp__healthy__echo") is True
    assert registry.has("mcp__flaky__echo") is False


@pytest.mark.asyncio
async def test_refresh_tools_failure_drops_zombie_client(tmp_path: Path) -> None:
    manager, created = await make_flaky_manager(tmp_path)
    await manager.add_server(server_config("flaky"))
    created["flaky"].fail_list_tools = True
    version_before = manager.version

    with pytest.raises(AgentError) as exc_info:
        await manager.refresh_tools("flaky")

    assert exc_info.value.code == "MCP_LIST_TOOLS_ERROR"
    assert await manager.get_client("flaky") is None
    assert manager.version == version_before + 1
    statuses = {status.id: status for status in await manager.list_servers()}
    assert statuses["flaky"].connected is False
    assert statuses["flaky"].tool_count == 0


@pytest.mark.asyncio
async def test_failed_server_recovers_after_reconnect(tmp_path: Path) -> None:
    manager, created = await make_flaky_manager(tmp_path)
    await manager.add_server(server_config("flaky"))
    registry = ToolRegistry()
    bridge = MCPToolBridge(manager, registry)
    created["flaky"].fail_list_tools = True

    assert await bridge.sync_all() == 0
    assert registry.has("mcp__flaky__echo") is False

    created["flaky"].fail_list_tools = False
    await manager.connect_server("flaky")
    assert await bridge.sync_if_needed() == 1
    assert registry.has("mcp__flaky__echo") is True


@pytest.mark.asyncio
async def test_disconnect_server_survives_unclean_client_disconnect(tmp_path: Path) -> None:
    manager, _created = await make_flaky_manager(tmp_path, client_cls=BrokenDisconnectClient)
    await manager.add_server(server_config("broken"))
    version_before = manager.version

    status = await manager.disconnect_server("broken")

    assert status.connected is False
    assert await manager.get_client("broken") is None
    assert manager.version == version_before + 1
