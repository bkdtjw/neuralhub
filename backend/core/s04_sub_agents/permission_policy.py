from __future__ import annotations

from backend.common.errors import AgentError
from backend.common.types import ToolResult
from backend.core.s02_tools import ToolRegistry

from .readonly_guard import is_readonly_blocked
from .runtime_models import IsolatedRegistryConfig

RECURSIVE_TOOL_NAMES = {"dispatch_agent", "orchestrate_agents"}
DEFAULT_READONLY_TOOLS = {"Read", "Bash"}
DEFAULT_READWRITE_TOOLS = {"Read", "Write", "Bash"}


class PermissionPolicyError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(code="SUB_AGENT_PERMISSION_ERROR", message=message)


def _resolve_allowed_tools(config: IsolatedRegistryConfig) -> set[str]:
    if config.allowed_tool_names:
        return set(config.allowed_tool_names) - RECURSIVE_TOOL_NAMES
    if config.permission_level == "readonly":
        return set(DEFAULT_READONLY_TOOLS)
    return set(DEFAULT_READWRITE_TOOLS)


def build_isolated_registry(
    parent_registry: ToolRegistry,
    config: IsolatedRegistryConfig,
) -> ToolRegistry:
    """Build a filtered registry for a sub-agent execution."""

    _ = config.workspace
    child_registry = ToolRegistry()
    allowed = _resolve_allowed_tools(config)
    for definition in parent_registry.list_definitions():
        if definition.name in RECURSIVE_TOOL_NAMES:
            continue
        if definition.name not in allowed:
            continue
        registered = parent_registry.get(definition.name)
        if registered is None:
            continue
        _, executor = registered
        if config.permission_level == "readonly" and definition.name == "Write":
            continue
        if config.permission_level == "readonly" and definition.name == "Bash":
            original_executor = executor

            async def readonly_bash(
                args: dict[str, object],
                _exec=original_executor,
            ) -> ToolResult:
                try:
                    command = str(args.get("command", "")).strip()
                    if is_readonly_blocked(command):
                        raise PermissionPolicyError(f"readonly 模式下不允许执行修改命令: {command}")
                    return await _exec(args)
                except PermissionPolicyError as exc:
                    return ToolResult(output=f"权限拒绝: {exc.message}", is_error=True)
                except Exception as exc:
                    error = PermissionPolicyError(f"只读命令执行失败: {exc}")
                    return ToolResult(output=error.message, is_error=True)

            child_registry.register(definition, readonly_bash)
            continue
        child_registry.register(definition, executor)
    return child_registry


__all__ = [
    "PermissionPolicyError",
    "build_isolated_registry",
    "is_readonly_blocked",
]
