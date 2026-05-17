from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SiteConfig

logger = get_logger(component="site_registry")


def load_site_config(domain: str, config_dir: Path | None = None) -> SiteConfig:
    try:
        try:
            import yaml
        except ImportError as exc:
            raise AgentError("YAML_NOT_INSTALLED", "pyyaml is required for site registry") from exc
        root = config_dir or Path("config/sites")
        for path in root.glob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if _matches_domain(domain, data):
                return SiteConfig.model_validate(data)
        return SiteConfig(domain=domain)
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("site_config_load_failed", domain=domain, error=str(exc))
        raise AgentError("SITE_CONFIG_LOAD_ERROR", str(exc)) from exc


def _matches_domain(domain: str, data: dict[str, Any]) -> bool:
    host = _host_from_value(domain)
    configured = _host_from_value(str(data.get("domain", "")))
    if not host or not configured:
        return False
    host_parts = host.split(".")
    configured_parts = configured.split(".")
    if len(host_parts) < len(configured_parts):
        return False
    return host_parts[-len(configured_parts) :] == configured_parts


def _host_from_value(value: str) -> str:
    candidate = value.strip().lower()
    if not candidate:
        return ""
    parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
    host = parsed.hostname or candidate.split("/", 1)[0]
    return host.strip(".")


__all__ = ["load_site_config"]
