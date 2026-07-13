from __future__ import annotations

from typing import Any

from backend.common.types import (
    MCPToolInfo,
    ToolDefinition,
    ToolParameterSchema,
    ToolPermission,
)


def tool_prefix(server_id: str) -> str:
    return f"mcp__{server_id}__"


def build_definition(server_id: str, tool: MCPToolInfo) -> ToolDefinition:
    return ToolDefinition(
        name=f"{tool_prefix(server_id)}{tool.name}",
        description=tool.description or f"MCP tool {tool.name} from {server_id}",
        category="mcp",
        parameters=to_parameter_schema(tool.input_schema),
        permission=ToolPermission(requires_approval=True, sandboxed=False),
    )


def to_parameter_schema(input_schema: dict[str, Any]) -> ToolParameterSchema:
    return ToolParameterSchema(
        type=str(input_schema.get("type", "object")),
        description=str(input_schema.get("description", "")),
        required=list(input_schema.get("required", [])),
        properties=dict(input_schema.get("properties", {})),
    )


__all__ = ["build_definition", "to_parameter_schema", "tool_prefix"]
