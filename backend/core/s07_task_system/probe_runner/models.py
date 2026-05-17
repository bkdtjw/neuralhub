from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProbeResult(BaseModel):
    site_id: str
    user_id: str
    ok: bool
    detail: str = ""
    latency_ms: int = 0
    checked_at: datetime = Field(default_factory=datetime.now)


__all__ = ["ProbeResult"]
