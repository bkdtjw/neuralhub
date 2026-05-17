from __future__ import annotations

from backend.core.s02_tools.builtin.article_extractor import ImageRef
from backend.core.s02_tools.builtin.browser import SiteConfig

from .by_position import filter_by_position
from .by_size import filter_by_size
from .by_url import filter_by_url


def filter_images(images: list[ImageRef], site_config: SiteConfig | None = None) -> list[ImageRef]:
    config = site_config or SiteConfig()
    filtered = filter_by_size(images, config.image_min_width, config.image_min_height)
    filtered = filter_by_url(filtered, config.blocked_image_url_keywords)
    return filter_by_position(filtered, config.image_excluded_ancestor_selectors)


__all__ = ["filter_images", "filter_by_position", "filter_by_size", "filter_by_url"]
