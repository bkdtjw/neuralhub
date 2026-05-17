from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from backend.common.errors import AgentError
from backend.common.logging import get_logger

from .ad_blocker import install_route_blocker
from .context import BrowserSession
from .modal_detector import has_remaining_modal
from .models import PageResult, SiteConfig
from .popup_dismisser import dismiss_popups

logger = get_logger(component="browser_navigation")


async def load_url(url: str, site_config: SiteConfig | None = None) -> PageResult:
    config = site_config or SiteConfig()
    try:
        async with BrowserSession(config.user_id, config.storage_state_path) as session:
            page = await session.new_page()
            await install_route_blocker(page, config.ad_block_domains)
            await page.goto(url, wait_until=config.wait_until, timeout=config.timeout_ms)
            await dismiss_popups(page, config.popup_close_selectors)
            html = await page.content()
            current_url = str(getattr(page, "url", url))
            screenshot_path = await _capture_screenshot(page, current_url, config)
            return PageResult(
                url=current_url,
                html=html,
                screenshot_path=screenshot_path,
                login_required=_looks_like_login(current_url, config),
                unhandled_popup=await has_remaining_modal(page),
            )
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("browser_load_url_failed", url=url, error=str(exc))
        raise AgentError("BROWSER_LOAD_URL_ERROR", str(exc)) from exc


async def _capture_screenshot(page: object, current_url: str, config: SiteConfig) -> Path | None:
    try:
        if config.screenshot_dir is None:
            return None
        config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(current_url.encode("utf-8")).hexdigest()[:16]
        path = config.screenshot_dir / f"{digest}.png"
        await page.screenshot(path=str(path), full_page=True)  # type: ignore[attr-defined]
        return path
    except Exception as exc:  # noqa: BLE001
        logger.error("browser_screenshot_failed", url=current_url, error=str(exc))
        raise AgentError("BROWSER_SCREENSHOT_ERROR", str(exc)) from exc


def _looks_like_login(url: str, config: SiteConfig) -> bool:
    path = urlparse(url).path.lower()
    return any(fragment.lower() in path for fragment in config.login_path_fragments)


__all__ = ["load_url"]
