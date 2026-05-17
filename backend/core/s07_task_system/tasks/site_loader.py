from __future__ import annotations

from pathlib import Path

from backend.common.errors import AgentError
from backend.core.s02_tools.builtin.browser import SiteConfig


def load_site_configs(config_dir: Path = Path("config/sites")) -> list[SiteConfig]:
    try:
        try:
            import yaml
        except ImportError as exc:
            raise AgentError("YAML_NOT_INSTALLED", "pyyaml is required") from exc
        configs: list[SiteConfig] = []
        for path in sorted(config_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                configs.append(SiteConfig.model_validate(data))
        return configs
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SITE_CONFIGS_LOAD_ERROR", str(exc)) from exc


__all__ = ["load_site_configs"]
