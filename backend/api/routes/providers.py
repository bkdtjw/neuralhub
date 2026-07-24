from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.adapters.model_discovery import discover_models
from backend.adapters.provider_manager import ProviderManager
from backend.api.middleware.auth import verify_token
from backend.common import LLMError
from backend.common.types import ProviderConfig, ProviderType
from backend.schemas.provider import (
    AddProviderRequest,
    DetectModelsRequest,
    DetectModelsResponse,
    ProviderResponse,
    ProviderUpdateRequest,
    TestConnectionResponse,
)

router = APIRouter(
    prefix="/api/providers",
    tags=["providers"],
    dependencies=[Depends(verify_token)],
)
provider_manager = ProviderManager()
_PROVIDER_ALIASES = {
    "openai": "openai_compat",
    "openai_compatible": "openai_compat",
    "claude_compat": "anthropic",
    "anthropic_compat": "anthropic",
}


def _mask_api_key(api_key: str) -> str:
    return f"{api_key[:4]}***" if api_key else ""


def _normalize_provider_type(value: str) -> str:
    return _PROVIDER_ALIASES.get(value, value)


def _to_response(config: ProviderConfig) -> ProviderResponse:
    return ProviderResponse(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type.value,
        base_url=config.base_url,
        api_key_preview=_mask_api_key(config.api_key),
        default_model=config.default_model,
        available_models=config.available_models,
        enable_prompt_cache=config.enable_prompt_cache,
        prompt_cache_retention=config.prompt_cache_retention,
        extra_body=config.extra_body,
        is_default=config.is_default,
        enabled=config.enabled,
        roles=config.roles,
    )


def _to_http_error(error: LLMError) -> HTTPException:
    status_code = 400
    if error.code == "PROVIDER_NOT_FOUND":
        status_code = 404
    if error.code == "PROVIDER_EXISTS":
        status_code = 409
    return HTTPException(
        status_code=status_code, detail={"code": error.code, "message": error.message}
    )


@router.post("", response_model=ProviderResponse)
async def add_provider(body: AddProviderRequest) -> ProviderResponse:
    try:
        data = body.model_dump()
        data["provider_type"] = _normalize_provider_type(data["provider_type"])
        return _to_response(await provider_manager.add(ProviderConfig(**data)))
    except LLMError as exc:
        raise _to_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)}
        ) from exc


@router.get("", response_model=list[ProviderResponse])
async def list_providers() -> list[ProviderResponse]:
    try:
        return [_to_response(item) for item in await provider_manager.list_all()]
    except LLMError as exc:
        raise _to_http_error(exc) from exc


@router.put("/{id}", response_model=ProviderResponse)
async def update_provider(id: str, body: ProviderUpdateRequest) -> ProviderResponse:
    try:
        data: dict[str, Any] = body.model_dump(exclude_none=True)
        if "provider_type" in data:
            data["provider_type"] = ProviderType(_normalize_provider_type(data["provider_type"]))
        return _to_response(await provider_manager.update(id, **data))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_PROVIDER_TYPE", "message": str(exc)}
        ) from exc
    except LLMError as exc:
        raise _to_http_error(exc) from exc


@router.delete("/{id}")
async def delete_provider(id: str) -> dict[str, Any]:
    try:
        deleted = await provider_manager.remove(id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail={"code": "PROVIDER_NOT_FOUND", "message": f"Provider not found: {id}"},
            )
        return {"ok": True, "message": "Provider deleted"}
    except LLMError as exc:
        raise _to_http_error(exc) from exc


@router.post("/{id}/test", response_model=TestConnectionResponse)
async def test_provider(id: str) -> TestConnectionResponse:
    try:
        start = perf_counter()
        ok = await provider_manager.test_connection(id)
        return TestConnectionResponse(
            ok=ok,
            message="Connection successful" if ok else "Connection failed",
            latency_ms=int((perf_counter() - start) * 1000),
        )
    except LLMError as exc:
        raise _to_http_error(exc) from exc


@router.post("/detect-models", response_model=DetectModelsResponse)
async def detect_models(body: DetectModelsRequest) -> DetectModelsResponse:
    """探测该 base_url/key 实际可调用的模型列表；编辑态 key 留空时回落到已存储的凭据。"""
    try:
        provider_type = _normalize_provider_type(body.provider_type)
        base_url, api_key = body.base_url.strip(), body.api_key.strip()
        if body.provider_id and not api_key:
            stored = next(
                (item for item in await provider_manager.list_all() if item.id == body.provider_id),
                None,
            )
            if stored is not None:
                api_key = stored.api_key
                base_url = base_url or stored.base_url
        models = await discover_models(provider_type, base_url, api_key)
        return DetectModelsResponse(ok=True, models=models, message=f"发现 {len(models)} 个模型")
    except LLMError as exc:
        return DetectModelsResponse(ok=False, models=[], message=exc.message)


@router.put("/{id}/default", response_model=ProviderResponse)
async def set_default_provider(id: str) -> ProviderResponse:
    try:
        await provider_manager.set_default(id)
        providers = await provider_manager.list_all()
        provider = next((item for item in providers if item.id == id), None)
        if provider is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "PROVIDER_NOT_FOUND", "message": f"Provider not found: {id}"},
            )
        return _to_response(provider)
    except LLMError as exc:
        raise _to_http_error(exc) from exc


__all__ = ["router", "provider_manager"]
