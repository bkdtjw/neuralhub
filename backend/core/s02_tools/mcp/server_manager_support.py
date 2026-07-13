from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.common.types import MCPServerConfig, MCPServerStatus, MCPToolInfo

from .client import MCPClient
from .lifecycle import safe_disconnect

DEFAULT_MCP_SEED_PATH = Path(__file__).resolve().parents[3] / "config" / "mcp_servers.json"

logger = get_logger(component="mcp_server_manager")


def load_server_seed(seed_path: Path) -> list[MCPServerConfig]:
    try:
        if not seed_path.exists():
            return []
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
        rows = raw.get("servers", []) if isinstance(raw, dict) else []
        return [MCPServerConfig.model_validate(row) for row in rows]
    except Exception:
        return []


def require_server(server_id: str, servers: dict[str, MCPServerConfig]) -> MCPServerConfig:
    config = servers.get(server_id)
    if config is None:
        raise AgentError("MCP_SERVER_NOT_FOUND", f"MCP server not found: {server_id}")
    return config


def build_status(
    config: MCPServerConfig,
    clients: dict[str, object],
    tool_cache: dict[str, list[MCPToolInfo]],
) -> MCPServerStatus:
    client = clients.get(config.id)
    is_connected = bool(client and getattr(client, "is_connected", False))
    return MCPServerStatus(
        id=config.id,
        name=config.name,
        transport=config.transport,
        connected=is_connected,
        tool_count=len(tool_cache.get(config.id, [])),
        enabled=config.enabled,
    )


def missing_status(server_id: str) -> MCPServerStatus:
    return MCPServerStatus(
        id=server_id,
        name=server_id,
        transport="unknown",
        connected=False,
        tool_count=0,
        enabled=False,
    )


async def connect_server_state(
    server_id: str,
    servers: dict[str, MCPServerConfig],
    clients: dict[str, MCPClient],
    tool_cache: dict[str, list[MCPToolInfo]],
    client_factory: Callable[[MCPServerConfig], MCPClient],
    on_stale_client_dropped: Callable[[], None] | None = None,
) -> MCPServerStatus:
    created_client = False
    client: MCPClient | None = None
    try:
        config = require_server(server_id, servers)
        client = clients.get(server_id)
        created_client = client is None
        if created_client:
            client = client_factory(config)
        await client.connect()
        tool_cache[server_id] = await client.list_tools()
        if created_client:
            clients[server_id] = client
        return build_status(config, clients, tool_cache)
    except AgentError:
        await _drop_failed_client(
            server_id, clients, tool_cache, client, created_client, on_stale_client_dropped
        )
        raise
    except Exception as exc:
        await _drop_failed_client(
            server_id, clients, tool_cache, client, created_client, on_stale_client_dropped
        )
        raise AgentError("MCP_CONNECT_SERVER_ERROR", str(exc)) from exc


async def _drop_failed_client(
    server_id: str,
    clients: dict[str, MCPClient],
    tool_cache: dict[str, list[MCPToolInfo]],
    client: MCPClient | None,
    created_client: bool,
    on_stale_client_dropped: Callable[[], None] | None,
) -> None:
    """连接/取工具列表失败后清理 client，已存在的坏连接也要摘除，防止
    "connected 但不可用" 的僵尸状态卡死后续所有同步。"""
    tool_cache.pop(server_id, None)
    if client is None:
        return
    stale_dropped = not created_client and clients.pop(server_id, None) is not None
    await safe_disconnect(client)
    if stale_dropped:
        logger.warning("mcp_stale_client_dropped", server_id=server_id)
        if on_stale_client_dropped is not None:
            on_stale_client_dropped()


async def disconnect_server_state(
    server_id: str,
    servers: dict[str, MCPServerConfig],
    clients: dict[str, MCPClient],
    tool_cache: dict[str, list[MCPToolInfo]],
    ignore_missing: bool,
) -> MCPServerStatus | None:
    try:
        config = servers.get(server_id)
        client = clients.pop(server_id, None)
        tool_cache.pop(server_id, None)
        if client is not None and not await safe_disconnect(client):
            logger.warning("mcp_disconnect_unclean", server_id=server_id)
        if config is None and not ignore_missing:
            raise AgentError("MCP_SERVER_NOT_FOUND", f"MCP server not found: {server_id}")
        return build_status(config, clients, tool_cache) if config is not None else None
    except AgentError:
        raise
    except Exception as exc:
        raise AgentError("MCP_DISCONNECT_SERVER_ERROR", str(exc)) from exc


__all__ = [
    "DEFAULT_MCP_SEED_PATH",
    "build_status",
    "connect_server_state",
    "disconnect_server_state",
    "load_server_seed",
    "missing_status",
    "require_server",
]
