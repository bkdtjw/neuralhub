from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.common.types import ToolArtifact, ToolResult

from .token_counter import estimate_tokens


@dataclass(frozen=True)
class ArtifactWriteRequest:
    output: str
    artifacts_dir: str
    session_id: str
    tool_call_id: str


def token_count(text: str) -> int:
    # 与 token_counter.estimate_tokens 同口径（CJK 加权），非空至少计 1。
    return max(1, estimate_tokens(text)) if text else 0


def sink_tool_result(result: ToolResult, artifacts_dir: str, session_id: str) -> ToolResult:
    if token_count(result.output) <= 500:
        return result
    path = write_artifact(
        ArtifactWriteRequest(
            output=result.output,
            artifacts_dir=artifacts_dir,
            session_id=session_id or "default",
            tool_call_id=result.tool_call_id,
        )
    )
    output = f"{extract_brief(result)}\n完整结果: {path}"
    return result.model_copy(
        update={
            "output": output,
            "artifacts": [
                *result.artifacts,
                ToolArtifact(kind="file", path=path, mime_type="application/json"),
            ],
        }
    )


def write_artifact(request: ArtifactWriteRequest) -> str:
    safe_sid = _safe_name(request.session_id)
    safe_call = _safe_name(request.tool_call_id or "tool")
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    root = Path(request.artifacts_dir).expanduser()
    directory = (root if root.is_absolute() else Path.cwd() / root) / safe_sid
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_call}_{timestamp}.json"
    path.write_text(_artifact_payload(request.output), encoding="utf-8")
    return path.resolve().as_posix()


def extract_brief(result: ToolResult) -> str:
    prefix = "[工具结果摘要:error]" if result.is_error else "[工具结果摘要]"
    first_line = result.output.strip().splitlines()[0] if result.output.strip() else ""
    parsed = _parse_json(result.output)
    if parsed is not None:
        return f"{prefix}\n{_brief_json(parsed)}"
    return f"{prefix}\n{_clip(first_line or result.output, 800)}"


def _artifact_payload(output: str) -> str:
    parsed = _parse_json(output)
    if parsed is None:
        parsed = {"raw": output}
    return json.dumps(parsed, ensure_ascii=False, indent=2, default=str)


def _brief_json(value: Any) -> str:
    if isinstance(value, list):
        return _clip(json.dumps(value[:3], ensure_ascii=False, default=str), 800)
    if isinstance(value, dict):
        keys = list(value)[:3]
        subset = {key: value[key] for key in keys}
        return _clip(json.dumps(subset, ensure_ascii=False, default=str), 800)
    return _clip(str(value), 800)


def _parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())[:80] or "default"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}...[truncated {len(text) - limit} chars]"
