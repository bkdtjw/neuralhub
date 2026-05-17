from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="storage_state_store")
_DEFAULT_ROOT = Path(os.getenv("STORAGE_STATE_DIR", "/tmp/agent-studio-storage-state"))
_DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60


class StorageStateCookie(BaseModel):
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float | None = Field(default=None, alias="expirationDate")
    http_only: bool = Field(default=False, alias="httpOnly")
    secure: bool = False
    same_site: str | None = Field(default=None, alias="sameSite")

    model_config = {"populate_by_name": True}


class StorageStatePayload(BaseModel):
    user_id: str
    domain: str
    cookies: list[StorageStateCookie] = Field(default_factory=list)
    local_storage: dict[str, str] = Field(default_factory=dict)
    origin: str | None = None


class StorageStateStore:
    def __init__(self, root: Path | None = None, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self.root = root or _DEFAULT_ROOT
        self.ttl_seconds = ttl_seconds

    def save(self, payload: StorageStatePayload) -> Path:
        try:
            path = self.load_state_path(payload.user_id, payload.domain)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_to_playwright_state(payload), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return path
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "storage_state_save_failed",
                user_id=payload.user_id,
                domain=payload.domain,
                error=str(exc),
            )
            raise AgentError("STORAGE_STATE_SAVE_ERROR", str(exc)) from exc

    def load_state_path(self, user_id: str, domain: str) -> Path:
        try:
            safe_user = _safe_part(user_id)
            safe_domain = _safe_part(_normalize_domain(domain))
            return self.root / safe_user / safe_domain / "storage_state.json"
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "storage_state_path_failed",
                user_id=user_id,
                domain=domain,
                error=str(exc),
            )
            raise AgentError("STORAGE_STATE_PATH_ERROR", str(exc)) from exc

    def is_state_fresh(self, user_id: str, domain: str) -> bool:
        try:
            path = self.load_state_path(user_id, domain)
            return path.exists() and time.time() - path.stat().st_mtime <= self.ttl_seconds
        except Exception as exc:  # noqa: BLE001
            logger.error("storage_state_fresh_check_failed", error=str(exc))
            raise AgentError("STORAGE_STATE_FRESH_CHECK_ERROR", str(exc)) from exc


def load_state_path(user_id: str, domain: str) -> Path:
    return StorageStateStore().load_state_path(user_id, domain)


def save(payload: StorageStatePayload) -> Path:
    return StorageStateStore().save(payload)


def is_state_fresh(user_id: str, domain: str) -> bool:
    return StorageStateStore().is_state_fresh(user_id, domain)


def _to_playwright_state(payload: StorageStatePayload) -> dict[str, Any]:
    origin = payload.origin or f"https://{_normalize_domain(payload.domain)}"
    return {
        "cookies": [_to_playwright_cookie(cookie) for cookie in payload.cookies],
        "origins": [
            {
                "origin": origin,
                "localStorage": [
                    {"name": key, "value": value}
                    for key, value in sorted(payload.local_storage.items())
                ],
            }
        ],
    }


def _to_playwright_cookie(cookie: StorageStateCookie) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "httpOnly": cookie.http_only,
        "secure": cookie.secure,
    }
    if cookie.expires is not None:
        data["expires"] = int(cookie.expires)
    if cookie.same_site:
        data["sameSite"] = _normalize_same_site(cookie.same_site)
    return data


def _normalize_same_site(value: str) -> str:
    lowered = value.lower()
    if lowered.endswith("lax"):
        return "Lax"
    if lowered.endswith("strict"):
        return "Strict"
    return "None"


def _normalize_domain(domain: str) -> str:
    return domain.strip().lower().lstrip(".")


def _safe_part(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return safe or "default"


__all__ = [
    "StorageStateCookie",
    "StorageStatePayload",
    "StorageStateStore",
    "is_state_fresh",
    "load_state_path",
    "save",
]
