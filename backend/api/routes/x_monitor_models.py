from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.storage.x_monitor_models import XMonitor, XMonitorHit


class XMonitorCreateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    interval_minutes: int = Field(ge=1)  # 下限随 settings 动态校验（路由层）
    days_window: int = Field(default=1, ge=1, le=30)
    search_type: Literal["Latest", "Top"] = "Latest"
    threshold_likes: int = Field(default=0, ge=0)
    threshold_views: int = Field(default=0, ge=0)
    enabled: bool = True

    @model_validator(mode="after")
    def require_some_threshold(self) -> XMonitorCreateRequest:
        # 两个阈值都为 0 会把每条新推文都当命中 → 告警风暴，直接拒绝。
        if self.threshold_likes <= 0 and self.threshold_views <= 0:
            raise ValueError("threshold_likes 与 threshold_views 至少设一个 > 0")
        return self


class XMonitorPatchRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=200)
    interval_minutes: int | None = Field(default=None, ge=1)
    days_window: int | None = Field(default=None, ge=1, le=30)
    search_type: Literal["Latest", "Top"] | None = None
    threshold_likes: int | None = Field(default=None, ge=0)
    threshold_views: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


class XMonitorResponse(BaseModel):
    id: str
    query: str
    interval_minutes: int
    days_window: int
    search_type: str
    threshold_likes: int
    threshold_views: int
    enabled: bool
    created_at: str
    last_run_at: str | None
    last_status: str

    @classmethod
    def from_monitor(cls, monitor: XMonitor) -> XMonitorResponse:
        return cls(
            **monitor.model_dump(exclude={"created_at", "last_run_at"}),
            created_at=monitor.created_at.isoformat(),
            last_run_at=monitor.last_run_at.isoformat() if monitor.last_run_at else None,
        )


class XMonitorListResponse(BaseModel):
    monitors: list[XMonitorResponse]


class XMonitorHitResponse(BaseModel):
    id: str
    monitor_id: str
    tweet_url: str
    author_handle: str
    text_snippet: str
    likes: int
    views: int
    hit_reason: str
    notified: bool
    created_at: str

    @classmethod
    def from_hit(cls, hit: XMonitorHit) -> XMonitorHitResponse:
        return cls(
            **hit.model_dump(exclude={"created_at"}),
            created_at=hit.created_at.isoformat(),
        )


class XMonitorHitListResponse(BaseModel):
    monitor_id: str
    hits: list[XMonitorHitResponse]


__all__ = [
    "XMonitorCreateRequest",
    "XMonitorHitListResponse",
    "XMonitorHitResponse",
    "XMonitorListResponse",
    "XMonitorPatchRequest",
    "XMonitorResponse",
]
