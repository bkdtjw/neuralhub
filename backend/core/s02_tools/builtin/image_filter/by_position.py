from __future__ import annotations

from backend.core.s02_tools.builtin.article_extractor import ImageRef


def filter_by_position(images: list[ImageRef], excluded_selectors: list[str]) -> list[ImageRef]:
    excluded = {selector.lower() for selector in excluded_selectors if selector}
    return [
        image
        for image in images
        if excluded.isdisjoint(selector.lower() for selector in image.parent_selectors)
    ]


__all__ = ["filter_by_position"]
