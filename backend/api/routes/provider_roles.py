from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.adapters.role_router import RoleRouter
from backend.api.middleware.auth import verify_token
from backend.api.routes.providers import provider_manager
from backend.common.errors import AgentError

router = APIRouter(
    prefix="/api/providers/role",
    tags=["providers"],
    dependencies=[Depends(verify_token)],
)


class ProviderRoleRequest(BaseModel):
    provider_id: str


@router.patch("/{role}")
async def set_provider_role(role: str, body: ProviderRoleRequest) -> dict[str, str]:
    try:
        await RoleRouter(provider_manager=provider_manager).set_role_default(role, body.provider_id)
        provider = await RoleRouter(provider_manager=provider_manager).resolve_provider(role)
        return {"role": role, "provider_id": provider.id}
    except AgentError as exc:
        status_code = 400 if exc.code not in {"PROVIDER_NOT_FOUND"} else 404
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


__all__ = ["ProviderRoleRequest", "router"]
