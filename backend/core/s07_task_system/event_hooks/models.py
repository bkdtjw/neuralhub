from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

HookStatus = Literal["developing", "stable", "escalating", "resolved"]


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("name must not be empty")
    return name


class HookTwitterConfig(BaseModel):
    accounts: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class HookSources(BaseModel):
    twitter: bool = True
    exa_web: bool = True
    zhipu_search: bool = True
    youtube: bool = False


class EventHook(BaseModel):
    id: str
    name: str
    twitter: HookTwitterConfig
    sources: HookSources
    cadence_minutes: int = Field(default=45, ge=1)
    materiality: int = Field(default=60, ge=0, le=100)
    enabled: bool = True
    created_at: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_name(value)


class TimelineEntry(BaseModel):
    ts: str
    text: str
    is_new: bool = True
    source: str


class Development(BaseModel):
    text: str
    ts: str = ""
    source: str = ""


class SourceHealth(BaseModel):
    source: str
    online: bool = False
    last_ok: str = ""


class HookState(BaseModel):
    hook_id: str
    status: HookStatus = "developing"
    summary: str = ""
    confidence: int = Field(default=0, ge=0, le=100)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    unseen_count: int = 0
    source_health: list[SourceHealth] = Field(default_factory=list)
    last_scanned: str = ""
    last_pushed_ts: str = ""
    # 冷却期内被拦下的重大进展标记：置 True 让 scheduler 在冷却过后补推，避免永久丢告警。
    # Pydantic 默认值保证旧持久化数据兼容；wire 自动带出，前端不消费也无害。
    pending_push: bool = False


class HookSummary(BaseModel):
    hook: EventHook
    state: HookState | None = None


class HookDraft(BaseModel):
    name: str
    twitter: HookTwitterConfig
    sources: HookSources
    cadence_minutes: int = Field(default=45, ge=1)
    materiality: int = Field(default=60, ge=0, le=100)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_name(value)


class HookSignal(BaseModel):
    source: str
    lane: str
    text: str
    url: str = ""
    author: str = ""
    ts: str = ""
    engagement: int = 0
    matched: list[str] = Field(default_factory=list)


class RetrievalOutcome(BaseModel):
    # 检索一个源（含多条 lane）的结果：signals 为已聚合的信号，
    # ok 反映该源本轮是否健康（全部 lane 都异常才 ok=False，部分成功仍 ok=True）。
    signals: list[HookSignal] = Field(default_factory=list)
    ok: bool = True


__all__ = [
    "Development",
    "EventHook",
    "HookDraft",
    "HookSignal",
    "HookSources",
    "HookState",
    "HookStatus",
    "HookSummary",
    "HookTwitterConfig",
    "RetrievalOutcome",
    "SourceHealth",
    "TimelineEntry",
]
