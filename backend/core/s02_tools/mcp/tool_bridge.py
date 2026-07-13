from __future__ import annotations

import asyncio
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import ToolResult
from backend.core.s02_tools.registry import ToolRegistry

from .bridge_support import build_definition, tool_prefix
from .server_manager import MCPServerManager

logger = get_logger(component="mcp_tool_bridge")


class MCPToolBridge:
    """Bridge MCP tools into the project's ToolRegistry."""

    def __init__(self, server_manager: MCPServerManager, registry: ToolRegistry) -> None:
        self._server_manager = server_manager
        self._registry = registry
        self._server_tools: dict[str, set[str]] = {}
        self._synced_version = -1
        self._lock = asyncio.Lock()

    def needs_sync(self) -> bool:
        return self._server_manager.version != self._synced_version

    async def sync_if_needed(self) -> int:
        try:
            if not self.needs_sync():
                return -1
            return await self.sync_all()
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_SYNC_IF_NEEDED_ERROR", str(exc)) from exc

    async def sync_server_tools(self, server_id: str) -> int:
        try:
            async with self._lock:
                return await self._sync_server_tools_locked(server_id)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_SYNC_SERVER_TOOLS_ERROR", str(exc)) from exc

    async def sync_all(self) -> int:
        try:
            async with self._lock:
                total = 0
                statuses = await self._server_manager.list_servers()
                active_ids = {
                    status.id for status in statuses if status.enabled and status.connected
                }
                for server_id in set(self._server_tools) - active_ids:
                    self._remove_server_tools_locked(server_id)
                for status in statuses:
                    if status.id in active_ids:
                        total += await self._sync_server_tools_degraded_locked(status.id)
                self._synced_version = self._server_manager.version
                return total
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_SYNC_ALL_TOOLS_ERROR", str(exc)) from exc

    async def sync_servers(self, server_ids: set[str]) -> int:
        try:
            async with self._lock:
                if not server_ids:
                    return 0
                total = 0
                statuses = await self._server_manager.list_servers()
                target_ids = {
                    status.id
                    for status in statuses
                    if status.enabled and status.id in server_ids
                }
                for server_id in set(self._server_tools) - target_ids:
                    self._remove_server_tools_locked(server_id)
                for status in statuses:
                    if status.id in target_ids:
                        total += await self._sync_server_tools_degraded_locked(status.id)
                self._synced_version = self._server_manager.version
                return total
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_SYNC_SERVERS_TOOLS_ERROR", str(exc)) from exc

    async def remove_server_tools(self, server_id: str) -> int:
        try:
            async with self._lock:
                return self._remove_server_tools_locked(server_id)
        except Exception as exc:
            raise AgentError("MCP_REMOVE_SERVER_TOOLS_ERROR", str(exc)) from exc

    async def _sync_server_tools_degraded_locked(self, server_id: str) -> int:
        """批量同步中单个 server 失败只降级（该 server 无工具），不拖垮聊天主链路。"""
        try:
            return await self._sync_server_tools_locked(server_id)
        except Exception as exc:
            logger.warning(
                "mcp_server_sync_skipped",
                server_id=server_id,
                error_code=getattr(exc, "code", None),
                error=str(exc),
            )
            return 0

    async def _sync_server_tools_locked(self, server_id: str) -> int:
        self._remove_server_tools_locked(server_id)
        tool_names: set[str] = set()
        for tool in await self._server_manager.refresh_tools(server_id):
            definition = build_definition(server_id, tool)
            self._registry.register(definition, self._build_executor(server_id, tool.name))
            tool_names.add(definition.name)
        self._server_tools[server_id] = tool_names
        return len(tool_names)

    def _remove_server_tools_locked(self, server_id: str) -> int:
        names = self._server_tools.pop(server_id, self._discover_names(server_id))
        removed = 0
        for name in names:
            if self._registry.remove(name):
                removed += 1
        return removed

    def _discover_names(self, server_id: str) -> set[str]:
        prefix = tool_prefix(server_id)
        return {
            tool.name
            for tool in self._registry.list_definitions()
            if tool.name.startswith(prefix)
        }

    def _build_executor(self, server_id: str, tool_name: str):
        async def execute(args: dict[str, Any]) -> ToolResult:
            retried = False
            for _ in range(2):
                try:
                    client = await self._server_manager.get_client(server_id)
                    if client is None or not client.is_connected:
                        await self._server_manager.connect_server(server_id)
                        client = await self._server_manager.get_client(server_id)
                    if client is None:
                        return ToolResult(
                            output=f"MCP server not connected: {server_id}",
                            is_error=True,
                        )
                    result = await client.call_tool(tool_name, args)
                    return ToolResult(output=result.content, is_error=result.is_error)
                except AgentError as exc:
                    if not retried and await self._should_retry(server_id, exc):
                        retried = True
                        continue
                    message = (
                        f"MCP tool failed after retry: {exc.message}"
                        if retried
                        else f"MCP tool error: {exc.message}"
                    )
                    return ToolResult(output=message, is_error=True)
                except Exception as exc:
                    return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=f"MCP tool failed after retry: {tool_name}", is_error=True)

        return execute

    async def _should_retry(self, server_id: str, exc: AgentError) -> bool:
        retryable_codes = {
            "MCP_CALL_TOOL_TIMEOUT",
            "MCP_CONNECT_TIMEOUT",
            "MCP_CONNECT_ERROR",
            "MCP_SESSION_MISSING",
        }
        if exc.code in retryable_codes:
            return True
        client = await self._server_manager.get_client(server_id)
        return client is not None and not client.is_connected

__all__ = ["MCPToolBridge"]
