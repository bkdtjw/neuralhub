from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.config.settings import settings
from backend.storage.storage_state_store import (
    StorageStateCookie,
    StorageStatePayload,
    StorageStateStore,
)

logger = get_logger(component="cookie_sync_route")

router = APIRouter(prefix="/api/cookie", tags=["cookie"])


class CookieSyncRequest(BaseModel):
    user_id: str
    domain: str
    cookies: list[StorageStateCookie] = Field(default_factory=list)
    local_storage: dict[str, str] = Field(default_factory=dict)
    origin: str | None = None
    token: str = ""


@router.post("/sync")
async def sync_cookie(payload: CookieSyncRequest, request: Request) -> dict[str, str]:
    try:
        token = (
            payload.token
            or _extract_bearer(request)
            or request.headers.get("X-Agent-Studio-Token", "")
        )
        if token != settings.auth_secret:
            raise HTTPException(status_code=401, detail="invalid token")
        state_path = StorageStateStore().save(
            StorageStatePayload(
                user_id=payload.user_id,
                domain=payload.domain,
                cookies=payload.cookies,
                local_storage=payload.local_storage,
                origin=payload.origin,
            )
        )
        return {"status": "ok", "path": str(state_path)}
    except HTTPException:
        raise
    except AgentError as exc:
        logger.error("cookie_sync_failed", code=exc.code, error=exc.message)
        raise HTTPException(status_code=500, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("cookie_sync_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="cookie sync failed") from exc


def _extract_bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    prefix = "Bearer "
    return value[len(prefix) :] if value.startswith(prefix) else ""


__all__ = ["router"]
