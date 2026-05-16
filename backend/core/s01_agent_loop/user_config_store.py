from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ValidationError


class UserConfig(BaseModel):
    owner_id: str
    auto_approve_tools: bool = False


class UserConfigStore:
    """JSON storage for owner-scoped user preferences."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir or "data/user_configs")
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def get(self, owner_id: str) -> UserConfig:
        path = self._path_for(owner_id)
        if not path.exists():
            return UserConfig(owner_id=owner_id)
        try:
            return UserConfig.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError):
            return UserConfig(owner_id=owner_id)

    def save(self, config: UserConfig) -> None:
        path = self._path_for(config.owner_id)
        tmp = path.with_suffix(".tmp")
        bak = path.with_suffix(".bak")
        tmp.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        if path.exists():
            path.replace(bak)
        tmp.replace(path)

    def _path_for(self, owner_id: str) -> Path:
        digest = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()
        return self._base_dir / f"{digest}.json"


__all__ = ["UserConfig", "UserConfigStore"]
