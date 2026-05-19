from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_FILE_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class StepStatus(str, Enum):
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    step_id: int
    request_id: str
    status: StepStatus
    task: str
    result_summary: str = ""
    key_data: dict[str, Any] = Field(default_factory=dict)
    files_touched: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    artifact_path: str | None = None
    next_blocked_by: list[int] = Field(default_factory=list)
    duration_s: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)


class StepResultStore:
    def __init__(self, base_dir: str | Path = "data/steps") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def write(self, session_id: str, result: StepResult) -> Path:
        path = self._path_for(session_id, result.step_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(path)
        return path

    def read(self, session_id: str, step_id: int) -> StepResult | None:
        path = self._path_for(session_id, step_id)
        if not path.exists():
            return None
        return StepResult.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, session_id: str) -> list[StepResult]:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return []
        results: list[StepResult] = []
        for path in sorted(session_dir.glob("step_*.json"), key=_step_sort_key):
            try:
                results.append(StepResult.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return results

    def _path_for(self, session_id: str, step_id: int) -> Path:
        if step_id < 1:
            raise ValueError(f"Invalid step_id: {step_id}")
        return self._session_dir(session_id) / f"step_{step_id}.json"

    def _session_dir(self, session_id: str) -> Path:
        _validate_file_part(session_id, "session_id")
        return self._base_dir / session_id


def _validate_file_part(value: str, field_name: str) -> None:
    if not value or not _FILE_PART_RE.fullmatch(value):
        raise ValueError(f"Invalid {field_name}: {value}")


def _step_sort_key(path: Path) -> int:
    try:
        return int(path.stem.removeprefix("step_"))
    except ValueError:
        return 0


__all__ = ["StepResult", "StepResultStore", "StepStatus"]
