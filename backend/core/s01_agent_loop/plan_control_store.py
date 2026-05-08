from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ControlAction = Literal["", "pause", "resume", "stop"]


class PlanControlSignal(BaseModel):
    action: ControlAction = ""
    instruction: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PlanControlStore:
    def __init__(self, base_dir: str | None = None) -> None:
        root = base_dir or os.environ.get("PLAN_CONTROL_DIR") or "data/plan_controls"
        self._base_dir = Path(root)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def request_pause(self, session_id: str) -> None:
        self._write(session_id, PlanControlSignal(action="pause"))

    def request_stop(self, session_id: str) -> None:
        self._write(session_id, PlanControlSignal(action="stop"))

    def request_resume(self, session_id: str, instruction: str = "") -> None:
        self._write(session_id, PlanControlSignal(action="resume", instruction=instruction.strip()))

    def read(self, session_id: str) -> PlanControlSignal:
        path = self._path_for(session_id)
        if not path.exists():
            return PlanControlSignal()
        try:
            return PlanControlSignal.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return PlanControlSignal()

    def clear(self, session_id: str) -> None:
        try:
            self._path_for(session_id).unlink(missing_ok=True)
        except OSError:
            pass

    def _write(self, session_id: str, signal: PlanControlSignal) -> None:
        self._path_for(session_id).write_text(signal.model_dump_json(), encoding="utf-8")

    def _path_for(self, session_id: str) -> Path:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
        return self._base_dir / f"{digest}.json"


__all__ = ["PlanControlSignal", "PlanControlStore"]
