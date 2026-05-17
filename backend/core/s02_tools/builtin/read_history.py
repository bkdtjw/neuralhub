from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.common.types import (
    ToolDefinition,
    ToolExecuteFn,
    ToolParameterSchema,
    ToolPermission,
    ToolResult,
)

ALLOWED_ROOTS = ("data/artifacts", "data/sessions", "data/steps")
MAX_RETURN_CHARS = 2000


def create_read_history_tool() -> tuple[ToolDefinition, ToolExecuteFn]:
    definition = ToolDefinition(
        name="read_history",
        description=(
            "当压缩摘要或 Level 1 工具结果摘要中的信息不足以完成当前任务时，"
            "从历史文件中检索具体内容。输入文件路径和查询关键词，返回匹配的片段（≤500 token）。"
        ),
        category="file-ops",
        parameters=ToolParameterSchema(
            properties={
                "file_path": {
                    "type": "string",
                    "description": "摘要中引用的文件路径，如 data/artifacts/.../product_search_xxx.json",
                },
                "query": {"type": "string", "description": "要查找的内容关键词"},
            },
            required=["file_path", "query"],
        ),
        permission=ToolPermission(
            requires_approval=False,
            sandboxed=True,
            allowed_paths=list(ALLOWED_ROOTS),
        ),
        side_effect=False,
    )

    async def execute(args: dict[str, object]) -> ToolResult:
        try:
            file_path = str(args.get("file_path", "")).strip()
            query = str(args.get("query", "")).strip()
            if not file_path or not query:
                return ToolResult(output="file_path and query are required", is_error=True)
            path = _resolve_allowed(file_path)
            if not path.is_file():
                return ToolResult(output=f"History file not found: {file_path}", is_error=True)
            output = _search_file(path, query)
            return ToolResult(output=_clip(output))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=str(exc), is_error=True)

    return definition, execute


def _resolve_allowed(file_path: str) -> Path:
    cwd = Path.cwd().resolve()
    requested = (cwd / file_path).resolve() if not Path(file_path).is_absolute() else Path(file_path).resolve()
    roots = [(cwd / root).resolve() for root in ALLOWED_ROOTS]
    if not any(requested == root or root in requested.parents for root in roots):
        raise ValueError("file_path must be under data/artifacts, data/sessions, or data/steps")
    return requested


def _search_file(path: Path, query: str) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        return _search_json(text, query)
    if path.suffix == ".jsonl":
        return _search_jsonl(text, query)
    return _search_text(text, query)


def _search_json(text: str, query: str) -> str:
    data = json.loads(text)
    if query.startswith("."):
        return json.dumps(_json_path(data, query), ensure_ascii=False, indent=2, default=str)
    return _search_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), query)


def _search_jsonl(text: str, query: str) -> str:
    matches: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if query.startswith("."):
            try:
                matches.append(json.dumps(_json_path(json.loads(line), query), ensure_ascii=False))
            except Exception:
                continue
        elif _contains(line, query):
            matches.append(line)
    return "\n".join(matches) or "未找到匹配片段"


def _search_text(text: str, query: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text)
    matches = [part.strip() for part in paragraphs if _contains(part, query)]
    if not matches:
        lines = [line for line in text.splitlines() if _contains(line, query)]
        matches = lines
    return "\n\n".join(matches) if matches else "未找到匹配片段"


def _json_path(data: Any, expression: str) -> Any:
    current = data
    for token in _path_tokens(expression):
        if isinstance(token, int):
            current = current[token]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError(f"Cannot select {token!r}")
    return current


def _path_tokens(expression: str) -> list[str | int]:
    path = expression.strip().lstrip(".")
    if not path:
        return []
    tokens: list[str | int] = []
    for part in path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)])?", part)
        if not match:
            raise ValueError(f"Unsupported json path: {expression}")
        tokens.append(match.group(1))
        if match.group(2) is not None:
            tokens.append(int(match.group(2)))
    return tokens


def _contains(text: str, query: str) -> bool:
    return query.lower() in text.lower()


def _clip(text: str) -> str:
    return text if len(text) <= MAX_RETURN_CHARS else text[:MAX_RETURN_CHARS]
