from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .file_search_support import FileSearchToolError, iter_matching_files, relative_path


class GlobMatch(BaseModel):
    path: str


class GlobResult(BaseModel):
    matches: list[GlobMatch] = Field(default_factory=list)
    truncated: bool = False


def create_glob_tool(base_path: str) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="Glob",
        description="Find files in the workspace by glob pattern without using shell commands.",
        category="file-ops",
        parameters=ToolParameterSchema(
            properties={
                "pattern": {"type": "string", "description": "Glob pattern such as **/*.py"},
                "max_results": {"type": "integer", "description": "Maximum file paths to return"},
            },
            required=["pattern"],
        ),
        side_effect=False,
    )
    root = Path(base_path).resolve()

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            pattern = str(args.get("pattern", "")).strip()
            max_results = _max_results(args.get("max_results"))
            paths = iter_matching_files(root, pattern)
            limited = paths[:max_results]
            result = GlobResult(
                matches=[GlobMatch(path=relative_path(root, path)) for path in limited],
                truncated=len(paths) > max_results,
            )
            return ToolResult(output=result.model_dump_json())
        except FileSearchToolError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute


def _max_results(value: object) -> int:
    try:
        return min(max(int(value or 200), 1), 1000)
    except (TypeError, ValueError):
        return 200


__all__ = ["create_glob_tool"]
