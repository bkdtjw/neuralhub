from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from backend.common.errors import AgentError
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.mcp import MCPServerManager, MCPToolBridge


@dataclass(frozen=True)
class RuntimeRegistryKey:
    """影响发往 LLM 的工具定义序列的请求维度。"""

    workspace: str
    mode: str
    model: str
    provider_id: str


@dataclass
class CachedRuntime:
    registry: ToolRegistry
    bridge: MCPToolBridge


_MAX_ENTRIES = 8
_cache: OrderedDict[RuntimeRegistryKey, CachedRuntime] = OrderedDict()
_lock = asyncio.Lock()


async def get_runtime_registry(
    key: RuntimeRegistryKey,
    server_manager: MCPServerManager,
    build: Callable[[ToolRegistry], None],
) -> CachedRuntime:
    """按 key 复用工具注册表与 MCP bridge。

    同 key 请求复用同一 registry：发往 LLM 的 tools 序列跨请求字节稳定，
    provider prompt cache 才能命中；MCP 工具仅在配置版本变化时重新同步。
    注意：注册期闭包（adapter、parent_task_id）固化为该 key 首次构建时的值。
    """
    try:
        async with _lock:
            cached = _cache.get(key)
            if cached is None:
                registry = ToolRegistry()
                build(registry)
                cached = CachedRuntime(
                    registry=registry,
                    bridge=MCPToolBridge(server_manager, registry),
                )
                _cache[key] = cached
                if len(_cache) > _MAX_ENTRIES:
                    _cache.popitem(last=False)
            else:
                _cache.move_to_end(key)
        await cached.bridge.sync_if_needed()
        return cached
    except AgentError:
        raise
    except Exception as exc:
        raise AgentError("RUNTIME_REGISTRY_CACHE_ERROR", str(exc)) from exc


def reset_runtime_registry_cache() -> None:
    _cache.clear()


__all__ = [
    "CachedRuntime",
    "RuntimeRegistryKey",
    "get_runtime_registry",
    "reset_runtime_registry_cache",
]
