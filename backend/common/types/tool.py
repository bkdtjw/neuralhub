from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, TypeAlias

from pydantic import BaseModel, Field

from .message import ToolResult

ToolCategory = Literal[
    "file-ops",
    "shell",
    "search",
    "browser",
    "git",
    "code-analysis",
    "mcp",
]


class ToolParameterSchema(BaseModel):
    type: str = "object"
    description: str = ""
    required: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class ToolPermission(BaseModel):
    requires_approval: bool = False
    sandboxed: bool = True
    allowed_paths: list[str] | None = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    category: ToolCategory
    parameters: ToolParameterSchema
    permission: ToolPermission = Field(default_factory=ToolPermission)
    side_effect: bool = True


ToolExecuteFn: TypeAlias = Callable[[dict[str, Any]], Awaitable[ToolResult]]


__all__ = [
    "ToolCategory",
    "ToolParameterSchema",
    "ToolPermission",
    "ToolDefinition",
    "ToolExecuteFn",
]
