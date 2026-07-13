from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from backend.common.errors import AgentError
from backend.common.types import MCPServerConfig, MCPServerStatus, MCPToolInfo
from backend.storage import MCPServerStore

from . import server_manager_support as support
from .client import MCPClient
from .lifecycle import create_connected_client, safe_disconnect


class MCPServerManager:
    def __init__(
        self,
        config_path: str | None = None,
        client_factory: Callable[[MCPServerConfig], MCPClient] | None = None,
        store: MCPServerStore | None = None,
    ) -> None:
        self._seed_path = Path(config_path) if config_path else support.DEFAULT_MCP_SEED_PATH
        self._store = store or MCPServerStore()
        self._client_factory = client_factory or MCPClient
        self._servers: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._tool_cache: dict[str, list[MCPToolInfo]] = {}
        self._version = 0
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._initialized = False

    @property
    def version(self) -> int:
        return self._version

    async def add_server(self, config: MCPServerConfig) -> str:
        try:
            await self._ensure_initialized()
            async with self._lock:
                if config.id in self._servers:
                    raise AgentError("MCP_SERVER_EXISTS", f"MCP server already exists: {config.id}")
                client: MCPClient | None = None
                tools: list[MCPToolInfo] = []
                if config.enabled:
                    client, tools = await create_connected_client(self._client_factory, config)
                try:
                    await self._store.add(config)
                except Exception:
                    if client is not None:
                        await safe_disconnect(client)
                    raise
                self._servers[config.id] = config
                if client is not None:
                    self._clients[config.id] = client
                    self._tool_cache[config.id] = tools
                self._bump_version()
                return config.id
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_ADD_SERVER_ERROR", str(exc)) from exc

    async def remove_server(self, server_id: str) -> bool:
        try:
            await self._ensure_initialized()
            async with self._lock:
                config = self._servers.pop(server_id, None)
                if config is None:
                    return False
                client = self._clients.pop(server_id, None)
                self._tool_cache.pop(server_id, None)
                if client is not None:
                    await safe_disconnect(client)
                await self._store.remove(server_id)
                self._bump_version()
                return True
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_REMOVE_SERVER_ERROR", str(exc)) from exc

    async def list_servers(self) -> list[MCPServerStatus]:
        try:
            await self._ensure_initialized()
            async with self._lock:
                return [
                    support.build_status(config, self._clients, self._tool_cache)
                    for config in self._servers.values()
                ]
        except Exception as exc:
            raise AgentError("MCP_LIST_SERVERS_ERROR", str(exc)) from exc

    async def get_client(self, server_id: str) -> MCPClient | None:
        try:
            await self._ensure_initialized()
            async with self._lock:
                return self._clients.get(server_id)
        except Exception as exc:
            raise AgentError("MCP_GET_CLIENT_ERROR", str(exc)) from exc

    async def refresh_tools(self, server_id: str) -> list[MCPToolInfo]:
        try:
            await self._ensure_initialized()
            async with self._lock:
                await support.connect_server_state(
                    server_id,
                    self._servers,
                    self._clients,
                    self._tool_cache,
                    self._client_factory,
                    on_stale_client_dropped=self._bump_version,
                )
                return list(self._tool_cache.get(server_id, []))
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_REFRESH_TOOLS_ERROR", str(exc)) from exc

    async def disconnect_all(self) -> None:
        try:
            await self._ensure_initialized()
            async with self._lock:
                for server_id in list(self._clients):
                    await support.disconnect_server_state(
                        server_id,
                        self._servers,
                        self._clients,
                        self._tool_cache,
                        ignore_missing=True,
                    )
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_DISCONNECT_ALL_ERROR", str(exc)) from exc

    async def connect_server(self, server_id: str) -> MCPServerStatus:
        try:
            await self._ensure_initialized()
            async with self._lock:
                config = support.require_server(server_id, self._servers)
                client, tools = await create_connected_client(self._client_factory, config)
                old_client = self._clients.pop(server_id, None)
                if old_client is not None:
                    await safe_disconnect(old_client)
                self._clients[server_id] = client
                self._tool_cache[server_id] = tools
                self._bump_version()
                return support.build_status(config, self._clients, self._tool_cache)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_CONNECT_SERVER_ERROR", str(exc)) from exc

    async def disconnect_server(self, server_id: str, ignore_missing: bool = False) -> MCPServerStatus:  # noqa: E501
        try:
            await self._ensure_initialized()
            async with self._lock:
                status = await support.disconnect_server_state(
                    server_id,
                    self._servers,
                    self._clients,
                    self._tool_cache,
                    ignore_missing=ignore_missing,
                )
                self._bump_version()
                return status or support.missing_status(server_id)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_DISCONNECT_SERVER_ERROR", str(exc)) from exc

    async def _ensure_initialized(self) -> None:
        try:
            if self._initialized:
                return
            async with self._init_lock:
                if self._initialized:
                    return
                configs = await self._store.list_all()
                if not configs:
                    seeds = support.load_server_seed(self._seed_path)
                    if seeds:
                        await self._store.import_from_json(seeds)
                        configs = seeds
                self._servers = {item.id: item for item in configs}
                self._initialized = True
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("MCP_INIT_ERROR", str(exc)) from exc

    def _bump_version(self) -> None:
        self._version += 1


__all__ = ["MCPServerManager"]
