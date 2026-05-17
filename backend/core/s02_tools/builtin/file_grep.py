from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from backend.common.types import ToolDefinition, ToolExecuteFn, ToolParameterSchema, ToolResult

from .file_search_support import (
    FileSearchToolError,
    iter_matching_files,
    read_searchable_text,
    relative_path,
)


class GrepMatch(BaseModel):
    path: str
    line_number: int
    line: str


class GrepResult(BaseModel):
    matches: list[GrepMatch] = Field(default_factory=list)
    truncated: bool = False


def create_grep_tool(base_path: str) -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="Grep",
        description="Search text files in the workspace and return path, line number, and matching line.",
        category="file-ops",
        parameters=ToolParameterSchema(
            properties={
                "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
                "include": {"type": "string", "description": "Glob of files to search, default **/*"},
                "case_sensitive": {"type": "boolean", "description": "Whether matching is case-sensitive"},
                "regex": {"type": "boolean", "description": "Treat pattern as a regular expression"},
                "max_results": {"type": "integer", "description": "Maximum matches to return"},
            },
            required=["pattern"],
        ),
        side_effect=False,
    )
    root = Path(base_path).resolve()

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            options = _options(args)
            matcher = _compile_matcher(options.pattern, options.regex, options.case_sensitive)
            matches: list[GrepMatch] = []
            truncated = False
            for path in iter_matching_files(root, options.include):
                text = read_searchable_text(path)
                if text is None:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if not matcher(line):
                        continue
                    if len(matches) >= options.max_results:
                        truncated = True
                        break
                    matches.append(GrepMatch(path=relative_path(root, path), line_number=line_number, line=line))
                if truncated:
                    break
            return ToolResult(output=GrepResult(matches=matches, truncated=truncated).model_dump_json())
        except (FileSearchToolError, re.error, ValueError) as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute


class GrepOptions(BaseModel):
    pattern: str
    include: str = "**/*"
    case_sensitive: bool = True
    regex: bool = False
    max_results: int = 100


def _options(args: dict[str, object]) -> GrepOptions:
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    include = str(args.get("include", "**/*") or "**/*").strip() or "**/*"
    return GrepOptions(
        pattern=pattern,
        include=include,
        case_sensitive=_bool_arg(args.get("case_sensitive"), default=True),
        regex=_bool_arg(args.get("regex"), default=False),
        max_results=_max_results(args.get("max_results")),
    )


def _compile_matcher(pattern: str, regex: bool, case_sensitive: bool) -> Callable[[str], bool]:
    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern, flags)
        return lambda line: compiled.search(line) is not None
    needle = pattern if case_sensitive else pattern.lower()
    return lambda line: needle in (line if case_sensitive else line.lower())


def _bool_arg(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _max_results(value: object) -> int:
    try:
        return min(max(int(value or 100), 1), 1000)
    except (TypeError, ValueError):
        return 100


__all__ = ["create_grep_tool"]
