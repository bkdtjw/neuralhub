from __future__ import annotations

from backend.core.s02_tools.builtin.article_extractor import ImageRef


def filter_by_size(images: list[ImageRef], min_width: int, min_height: int) -> list[ImageRef]:
    return [
        image
        for image in images
        if _dimension_ok(image.width, min_width) and _dimension_ok(image.height, min_height)
    ]


def _dimension_ok(value: int | None, minimum: int) -> bool:
    return value is None or value >= minimum


__all__ = ["filter_by_size"]
