from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

from backend.common.errors import AgentError

from .models import ActionRoute, CardHandlerDeps


async def handle_provide_selector(route: ActionRoute, deps: CardHandlerDeps) -> dict:
    if not route.selector:
        return {"status": "selector_missing", "url": route.target}
    try:
        path = _site_path(route.target, deps.config_dir)
        await asyncio.to_thread(_append_selector, path, route.selector)
        return {"status": "selector_saved", "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SELECTOR_SAVE_ERROR", str(exc)) from exc


def _site_path(url: str, config_dir: Path) -> Path:
    host = urlparse(url).hostname or urlparse(f"//{url}").hostname or "site"
    return config_dir / f"{host.replace('.', '_')}.yaml"


def _append_selector(path: Path, selector: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
    except ImportError as exc:
        raise AgentError("YAML_NOT_INSTALLED", "pyyaml is required") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data if isinstance(data, dict) else {}
    selectors = list(data.get("popup_close_selectors") or [])
    if selector not in selectors:
        selectors.append(selector)
    data["popup_close_selectors"] = selectors
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


__all__ = ["handle_provide_selector"]
