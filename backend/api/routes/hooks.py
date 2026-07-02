from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.middleware.auth import verify_token
from backend.api.routes.hooks_api_models import (
    HookListResponse,
    HookLogResponse,
    HookOkResponse,
)
from backend.core.s07_task_system.event_hooks import (
    HookDraft,
    HookStore,
    HookSummary,
    run_hook,
)

router = APIRouter(
    prefix="/api/hooks",
    tags=["hooks"],
    dependencies=[Depends(verify_token)],
)


@router.get("", response_model=HookListResponse)
async def list_hooks(request: Request) -> HookListResponse:
    try:
        return HookListResponse(hooks=await _store(request).list_summaries())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_LIST_ERROR", str(exc)) from exc


@router.post("", response_model=HookSummary)
async def create_hook(request: Request, body: HookDraft) -> HookSummary:
    try:
        return await _store(request).create(body)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_CREATE_ERROR", str(exc)) from exc


@router.get("/{hook_id}", response_model=HookSummary)
async def get_hook(request: Request, hook_id: str) -> HookSummary:
    try:
        summary = await _store(request).get_summary(hook_id)
        if summary is None:
            raise _not_found()
        return summary
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_GET_ERROR", str(exc)) from exc


@router.put("/{hook_id}", response_model=HookSummary)
async def update_hook(request: Request, hook_id: str, body: HookDraft) -> HookSummary:
    try:
        summary = await _store(request).update(hook_id, body)
        if summary is None:
            raise _not_found()
        return summary
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_UPDATE_ERROR", str(exc)) from exc


@router.delete("/{hook_id}", response_model=HookOkResponse)
async def delete_hook(request: Request, hook_id: str) -> HookOkResponse:
    try:
        if not await _store(request).delete(hook_id):
            raise _not_found()
        return HookOkResponse(ok=True)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_DELETE_ERROR", str(exc)) from exc


@router.post("/{hook_id}/run", response_model=HookOkResponse)
async def run_hook_now(request: Request, hook_id: str) -> HookOkResponse:
    try:
        store = _store(request)
        summary = await store.get_summary(hook_id)
        if summary is None:
            raise _not_found()
        runtime = getattr(request.app.state, "hook_runtime", None)
        if runtime is None:
            raise _server_error("HOOK_RUNTIME_UNAVAILABLE", "扫描引擎未就绪", 503)
        await run_hook(
            summary.hook,
            store,
            twitter_search_fn=runtime.twitter_search_fn,
            assess_fn=runtime.assess_fn,
            push_fn=runtime.push_fn,
            exa_search_fn=getattr(runtime, "exa_search_fn", None),
        )
        return HookOkResponse(ok=True)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_RUN_ERROR", str(exc)) from exc


@router.post("/{hook_id}/seen", response_model=HookOkResponse)
async def mark_hook_seen(request: Request, hook_id: str) -> HookOkResponse:
    try:
        if await _store(request).mark_seen(hook_id) is None:
            raise _not_found()
        return HookOkResponse(ok=True)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_SEEN_ERROR", str(exc)) from exc


@router.post("/{hook_id}/revive", response_model=HookOkResponse)
async def revive_hook(request: Request, hook_id: str) -> HookOkResponse:
    try:
        if await _store(request).revive(hook_id) is None:
            raise _not_found()
        return HookOkResponse(ok=True)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_REVIVE_ERROR", str(exc)) from exc


@router.get("/{hook_id}/log", response_model=HookLogResponse)
async def get_hook_log(request: Request, hook_id: str) -> HookLogResponse:
    try:
        summary = await _store(request).get_summary(hook_id)
        if summary is None:
            raise _not_found()
        state = await _store(request).get_state(hook_id)
        return HookLogResponse(entries=state.timeline if state else [])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("HOOK_LOG_ERROR", str(exc)) from exc


def _store(request: Request) -> HookStore:
    store = getattr(request.app.state, "hook_store", None)
    if store is None:
        raise _server_error("HOOK_STORE_UNAVAILABLE", "钩子存储未就绪", 503)
    return store


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"message": "钩子不存在"})


def _server_error(code: str, message: str, status_code: int = 500) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


__all__ = ["router"]
