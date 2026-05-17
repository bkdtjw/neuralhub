from __future__ import annotations

from pathlib import Path

from backend.core.s02_tools.builtin.article_extractor.site_registry import load_site_config
from backend.core.s02_tools.builtin.browser import SiteConfig


def load_site_configs(config_dir: Path) -> list[SiteConfig]:
    configs: list[SiteConfig] = []
    for path in sorted(config_dir.glob("*.yaml")):
        config = load_site_config(path.stem, config_dir)
        if config.name or config.domain:
            configs.append(config)
    return configs


def resolve_site_config(site: str, config_dir: Path) -> SiteConfig | None:
    for config in load_site_configs(config_dir):
        if site in {config.name, config.domain}:
            return config
    return None


__all__ = ["load_site_configs", "resolve_site_config"]
