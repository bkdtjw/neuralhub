from __future__ import annotations

from pydantic import BaseModel

from backend.core.s02_tools.builtin.x_client import XPost


class XPostOut(BaseModel):
    author_name: str
    author_handle: str
    text: str
    likes: int
    retweets: int
    replies: int
    views: int
    created_at: str
    url: str

    @classmethod
    def from_post(cls, post: XPost) -> XPostOut:
        return cls(**post.model_dump())


class XSearchResponse(BaseModel):
    query: str
    count: int
    rate_limited: bool = False
    retry_after: int | None = None
    cached: bool = False
    results: list[XPostOut]


__all__ = ["XPostOut", "XSearchResponse"]
