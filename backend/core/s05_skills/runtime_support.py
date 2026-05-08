from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.adapters.base import LLMAdapter
from backend.common.errors import AgentError
from backend.common.types import AgentEventHandler
from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin.bash import create_bash_tool
from backend.core.s02_tools.mcp import MCPToolBridge
from backend.core.task_queue import TaskQueue

from .models import ToolConfig

_RECURSIVE_TOOL_NAMES = {"dispatch_agent", "orchestrate_agents", "spawn_agent"}


class FilteredBridge:
    def __init__(
        self,
        bridge: MCPToolBridge,
        registry: ToolRegistry,
        allowed_tools: set[str],
        required_mcp_servers: set[str],
    ) -> None:
        self._bridge = bridge
        self._registry = registry
        self._allowed_tools = allowed_tools
        self._required_mcp_servers = required_mcp_servers

    def needs_sync(self) -> bool:
        if not self._required_mcp_servers:
            return False
        return self._bridge.needs_sync()

    async def sync_all(self) -> int:
        try:
            count = 0
            if self._required_mcp_servers:
                count = await self._bridge.sync_servers(self._required_mcp_servers)
            self._prune_disallowed()
            return count
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("SKILL_RUNTIME_MCP_SYNC_ERROR", str(exc)) from exc

    async def sync_if_needed(self) -> int:
        try:
            if not self.needs_sync():
                return -1
            count = await self._bridge.sync_servers(self._required_mcp_servers)
            self._prune_disallowed()
            return count
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError("SKILL_RUNTIME_MCP_SYNC_ERROR", str(exc)) from exc

    def _prune_disallowed(self) -> None:
        if not self._allowed_tools:
            return
        for definition in list(self._registry.list_definitions()):
            if definition.name not in self._allowed_tools:
                self._registry.remove(definition.name)


def build_runtime_registry(
    register_tools: Callable[..., None],
    tools: ToolConfig,
    max_depth: int,
    workspace: str,
    adapter: LLMAdapter,
    model: str,
    session_id: str,
    task_queue: TaskQueue | None,
    event_handler: AgentEventHandler | None,
    runtime: Any,
    spec_registry: Any,
    is_sub_agent: bool,
) -> ToolRegistry:
    base_registry = ToolRegistry()
    register_tools(
        base_registry,
        workspace,
        adapter=adapter,
        default_model=model,
        agent_runtime=runtime,
        spec_registry=spec_registry,
        task_queue=task_queue,
        event_handler=event_handler,
        is_sub_agent=is_sub_agent,
        parent_task_id=session_id,
    )
    filtered = ToolRegistry()
    for definition in base_registry.list_definitions():
        if tools.allowed_tools and definition.name not in tools.allowed_tools:
            continue
        if max_depth <= 0 and definition.name in _RECURSIVE_TOOL_NAMES:
            continue
        registered = base_registry.get(definition.name)
        if registered is None:
            continue
        override = tools.tool_overrides.get(definition.name, {})
        if definition.name == "Bash" and isinstance(override.get("timeout"), int):
            filtered.register(*create_bash_tool(workspace, timeout=int(override["timeout"])))
            continue
        _, executor = registered
        filtered.register(definition, executor)
    return filtered


__all__ = ["FilteredBridge", "build_runtime_registry"]
