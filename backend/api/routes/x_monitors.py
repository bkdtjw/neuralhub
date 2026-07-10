from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.middleware.auth import verify_token
from backend.api.routes.x_monitor_models import (
    XMonitorCreateRequest,
    XMonitorHitListResponse,
    XMonitorHitResponse,
    XMonitorListResponse,
    XMonitorPatchRequest,
    XMonitorResponse,
)
from backend.config.settings import settings
from backend.storage.x_monitor_store import XMonitorStore

router = APIRouter(
    prefix="/api/x/monitors",
    tags=["x-monitors"],
    dependencies=[Depends(verify_token)],
)


def _store() -> XMonitorStore:
    return XMonitorStore()


def _check_interval(minutes: int | None) -> None:
    floor = settings.x_monitor_min_interval_minutes
    if minutes is not None and minutes < floor:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "X_MONITOR_INTERVAL_TOO_SMALL",
                "message": f"轮询间隔不能小于 {floor} 分钟（保护共享 X 账号额度）",
            },
        )


@router.post("", response_model=XMonitorResponse)
async def create_monitor(body: XMonitorCreateRequest) -> XMonitorResponse:
    _check_interval(body.interval_minutes)
    store = _store()
    if await store.count_monitors() >= settings.x_monitor_max_count:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "X_MONITOR_LIMIT_REACHED",
                "message": f"监控数量已达上限 {settings.x_monitor_max_count}，请先删除不用的监控",
            },
        )
    monitor = await store.create_monitor(body.model_dump())
    return XMonitorResponse.from_monitor(monitor)


@router.get("", response_model=XMonitorListResponse)
async def list_monitors() -> XMonitorListResponse:
    monitors = await _store().list_monitors()
    return XMonitorListResponse(monitors=[XMonitorResponse.from_monitor(m) for m in monitors])


@router.get("/{monitor_id}", response_model=XMonitorResponse)
async def get_monitor(monitor_id: str) -> XMonitorResponse:
    monitor = await _store().get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail={"code": "X_MONITOR_NOT_FOUND", "message": "监控不存在"})
    return XMonitorResponse.from_monitor(monitor)


@router.patch("/{monitor_id}", response_model=XMonitorResponse)
async def patch_monitor(monitor_id: str, body: XMonitorPatchRequest) -> XMonitorResponse:
    _check_interval(body.interval_minutes)
    monitor = await _store().update_monitor(monitor_id, body.model_dump(exclude_none=True))
    if monitor is None:
        raise HTTPException(status_code=404, detail={"code": "X_MONITOR_NOT_FOUND", "message": "监控不存在"})
    return XMonitorResponse.from_monitor(monitor)


@router.delete("/{monitor_id}")
async def delete_monitor(monitor_id: str) -> dict[str, bool]:
    deleted = await _store().delete_monitor(monitor_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "X_MONITOR_NOT_FOUND", "message": "监控不存在"})
    return {"deleted": True}


@router.get("/{monitor_id}/hits", response_model=XMonitorHitListResponse)
async def list_hits(
    monitor_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> XMonitorHitListResponse:
    store = _store()
    if await store.get_monitor(monitor_id) is None:
        raise HTTPException(status_code=404, detail={"code": "X_MONITOR_NOT_FOUND", "message": "监控不存在"})
    hits = await store.list_hits(monitor_id, limit)
    return XMonitorHitListResponse(
        monitor_id=monitor_id,
        hits=[XMonitorHitResponse.from_hit(hit) for hit in hits],
    )


__all__ = ["router"]
