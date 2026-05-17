from __future__ import annotations

from backend.core.s02_tools.builtin.article_extractor import ImageRef


def filter_by_url(images: list[ImageRef], blocked_keywords: list[str]) -> list[ImageRef]:
    blocked = [keyword.lower() for keyword in blocked_keywords if keyword]
    return [
        image
        for image in images
        if not any(keyword in image.url.lower() for keyword in blocked)
    ]


__all__ = ["filter_by_url"]
