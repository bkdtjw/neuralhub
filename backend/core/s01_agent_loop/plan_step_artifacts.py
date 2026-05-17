from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.common.types import Message, ToolResult

from .plan_models import TodoStep

OUTPUT_SUMMARY_LIMIT = 4000


def archive_agent_step(todo_step: TodoStep, messages: list[Message], steps_dir: Path) -> str:
    payload = [message.model_dump(mode="json") for message in messages]
    return _write_archive(todo_step, payload, steps_dir)


def archive_script_step(todo_step: TodoStep, result: ToolResult, steps_dir: Path) -> str:
    payload: dict[str, Any] = {"tool_result": result.model_dump(mode="json")}
    return _write_archive(todo_step, payload, steps_dir)


def summary_with_archive(summary: str, archive_path: str) -> str:
    suffix = f"\n完整步骤结果: {archive_path}"
    limit = max(0, OUTPUT_SUMMARY_LIMIT - len(suffix))
    return f"{summary[:limit]}{suffix}" if summary else suffix.strip()


def _write_archive(todo_step: TodoStep, payload: Any, steps_dir: Path) -> str:
    steps_dir.mkdir(parents=True, exist_ok=True)
    path = steps_dir / f"step_{todo_step.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path.as_posix()


__all__ = ["archive_agent_step", "archive_script_step", "summary_with_archive"]
