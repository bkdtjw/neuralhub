from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    id: str
    trigger: str
    lesson: str
    keywords: list[str] = Field(default_factory=list)
    source_session: str
    created_at: datetime
    hit_count: int = 0


class LongTermMemory(BaseModel):
    entries: list[MemoryEntry] = Field(default_factory=list)
