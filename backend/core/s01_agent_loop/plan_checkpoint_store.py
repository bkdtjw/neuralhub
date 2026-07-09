from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .plan_models import PlanState
from .plan_state_machine import TERMINAL_PHASES

_FILE_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_PLAN_PART_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PlanCheckpointStore:
    """JSON checkpoint storage for Plan & Execute runtime state."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or "data/plan_checkpoints")
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: PlanState) -> Path:
        state.updated_at = datetime.now()
        path = self._path_for(state.session_id, state.plan_name)
        tmp = path.with_suffix(".tmp")
        bak = path.with_suffix(".bak")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        if path.exists():
            path.replace(bak)
        tmp.replace(path)
        return path

    def load(self, session_id: str, plan_name: str) -> PlanState | None:
        path = self._path_for(session_id, plan_name)
        state = _load_state(path)
        if state is not None:
            return state
        return _load_state(path.with_suffix(".bak"))

    def load_latest(self, session_id: str) -> PlanState | None:
        latest_path = self._latest_path(session_id)
        if latest_path is None:
            return None
        state = _load_state(latest_path)
        if state is not None:
            return state
        return _load_state(latest_path.with_suffix(".bak"))

    def list_checkpoints(self, session_id: str) -> list[str]:
        _validate_file_part(session_id, "session_id")
        prefix_len = len(session_id) + 1
        return sorted(
            path.stem[prefix_len:]
            for path in self._base_dir.glob(f"{session_id}-*.json")
            if path.is_file()
        )

    def delete(self, session_id: str, plan_name: str) -> bool:
        path = self._path_for(session_id, plan_name)
        removed = False
        for candidate in (path, path.with_suffix(".bak"), path.with_suffix(".tmp")):
            if candidate.exists():
                candidate.unlink()
                removed = True
        return removed

    def find_incomplete_by_owner(self, owner_id: str) -> list[PlanState]:
        states: list[PlanState] = []
        paths = [path for path in self._base_dir.glob("*.json") if path.is_file()]
        paths.extend(
            path
            for path in self._base_dir.glob("*.bak")
            if path.is_file() and not path.with_suffix(".json").exists()
        )
        for path in sorted(paths):
            state = _load_state(path)
            if state is None:
                continue
            if state.owner_id == owner_id and state.phase not in TERMINAL_PHASES:
                states.append(state)
        return states

    def cleanup(self, max_age_days: int = 7) -> int:
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for path in sorted(self._base_dir.glob("*")):
            if not path.is_file() or path.suffix not in {".json", ".bak", ".tmp"}:
                continue
            if path.stat().st_mtime >= cutoff:
                continue
            state = _load_state(path) if path.suffix != ".tmp" else None
            if state is not None and state.phase not in TERMINAL_PHASES:
                continue
            path.unlink()
            removed += 1
        return removed

    def cleanup_stale(self, max_stale_days: int = 30) -> int:
        # 补 cleanup 的空白：cleanup 永久保留非终态 checkpoint，长期运行会线性堆积拖慢扫描。
        # 这里只删「能解析为非终态且 mtime 超龄」的 json/bak；终态与损坏文件仍交给 cleanup。
        cutoff = time.time() - max_stale_days * 86400
        removed = 0
        for path in sorted(self._base_dir.glob("*")):
            if not path.is_file() or path.suffix not in {".json", ".bak"}:
                continue
            if path.stat().st_mtime >= cutoff:
                continue
            state = _load_state(path)
            if state is None or state.phase in TERMINAL_PHASES:
                continue
            path.unlink()
            removed += 1
        return removed

    def _latest_path(self, session_id: str) -> Path | None:
        _validate_file_part(session_id, "session_id")
        paths = [path for path in self._base_dir.glob(f"{session_id}-*.json") if path.is_file()]
        if paths:
            return max(paths, key=lambda path: path.stat().st_mtime)
        backups = [path for path in self._base_dir.glob(f"{session_id}-*.bak") if path.is_file()]
        if not backups:
            return None
        latest_backup = max(backups, key=lambda path: path.stat().st_mtime)
        return latest_backup.with_suffix(".json")

    def _path_for(self, session_id: str, plan_name: str) -> Path:
        _validate_file_part(session_id, "session_id")
        _validate_plan_name(plan_name)
        return self._base_dir / f"{session_id}-{plan_name}.json"


def _load_state(path: Path) -> PlanState | None:
    if not path.exists():
        return None
    try:
        return PlanState.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, ValidationError):
        return None


def _validate_plan_name(name: str) -> None:
    if not _PLAN_PART_RE.fullmatch(name):
        raise ValueError(f"Invalid plan name: {name}")


def _validate_file_part(value: str, field_name: str) -> None:
    if not value or not _FILE_PART_RE.fullmatch(value):
        raise ValueError(f"Invalid {field_name}: {value}")


__all__ = ["PlanCheckpointStore"]
