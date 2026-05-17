from __future__ import annotations

from pydantic import BaseModel, Field


class ImageRef(BaseModel):
    url: str
    width: int | None = None
    height: int | None = None
    alt: str = ""
    parent_selectors: list[str] = Field(default_factory=list)


class Article(BaseModel):
    url: str
    title: str
    body: str
    images: list[ImageRef] = Field(default_factory=list)
    source: str = "fallback"


class SiteRule(BaseModel):
    name: str = ""
    domain: str = ""
    title_selectors: list[str] = Field(default_factory=list)
    content_selectors: list[str] = Field(default_factory=list)
    image_selectors: list[str] = Field(default_factory=list)


__all__ = ["Article", "ImageRef", "SiteRule"]
