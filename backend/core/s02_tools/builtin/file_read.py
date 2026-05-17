from __future__ import annotations

import os

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

MAX_READ_BYTES = 100 * 1024


def _is_safe_path(path: str) -> bool:
    if not path or os.path.isabs(path):
        return False
    return ".." not in path.replace("\\", "/").split("/")


def create_read_tool(base_path: str) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="Read",
        description="Read the contents of a file by relative path.",
        category="file-ops",
        parameters=ToolParameterSchema(
            properties={"path": {"type": "string", "description": "Relative file path"}},
            required=["path"],
        ),
        side_effect=False,
    )
    root = os.path.abspath(base_path)

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            relative_path = str(args.get("path", ""))
            if not _is_safe_path(relative_path):
                return ToolResult(output="Invalid path", is_error=True)
            full_path = os.path.abspath(os.path.join(root, relative_path))
            if not full_path.startswith(root + os.sep) and full_path != root:
                return ToolResult(output="Invalid path", is_error=True)
            if not os.path.isfile(full_path):
                return ToolResult(output=f"File not found: {relative_path}", is_error=True)
            if os.path.getsize(full_path) > MAX_READ_BYTES:
                return ToolResult(
                    output=f"File too large to read: {relative_path} exceeds 100KB",
                    is_error=True,
                )
            with open(full_path, "r", encoding="utf-8") as file:
                return ToolResult(output=file.read())
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute
