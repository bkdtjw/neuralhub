from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.storage.database import init_db
from backend.storage.session_store import SessionStore

if TYPE_CHECKING:
    from backend.storage.hook_config_store import HookConfigStore
    from backend.storage.memory_store import MemoryStore
    from backend.storage.mcp_server_store import MCPServerStore
    from backend.storage.provider_store import ProviderStore
    from backend.storage.sub_agent_task_store import SubAgentTaskStore
    from backend.storage.task_config_store import TaskConfigStore
    from backend.storage.x_monitor_store import XMonitorStore

__all__ = [
    "HookConfigStore",
    "MCPServerStore",
    "MemoryStore",
    "ProviderStore",
    "SessionStore",
    "SubAgentTaskStore",
    "TaskConfigStore",
    "XMonitorStore",
    "init_db",
]


def __getattr__(name: str) -> Any:
    if name == "HookConfigStore":
        from backend.storage.hook_config_store import HookConfigStore

        return HookConfigStore
    if name == "MCPServerStore":
        from backend.storage.mcp_server_store import MCPServerStore

        return MCPServerStore
    if name == "MemoryStore":
        from backend.storage.memory_store import MemoryStore

        return MemoryStore
    if name == "ProviderStore":
        from backend.storage.provider_store import ProviderStore

        return ProviderStore
    if name == "TaskConfigStore":
        from backend.storage.task_config_store import TaskConfigStore

        return TaskConfigStore
    if name == "SubAgentTaskStore":
        from backend.storage.sub_agent_task_store import SubAgentTaskStore

        return SubAgentTaskStore
    if name == "XMonitorStore":
        from backend.storage.x_monitor_store import XMonitorStore

        return XMonitorStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
