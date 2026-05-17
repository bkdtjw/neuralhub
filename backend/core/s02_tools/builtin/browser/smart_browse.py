from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from playwright.async_api import Page

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.storage.storage_state_store import StorageStateStore

from .ad_blocker import install_route_blocker
from .context import BrowserSession
from .popup_dismisser import dismiss_popups

logger = get_logger(component="browser_smart_browse")


class SmartPage:
    """Thin wrapper that auto-dismisses popups after goto.

    Wrapped methods with custom behavior:
      - goto(url, **kwargs): page.goto + dismiss_popups
      - dismiss_popups(): explicit popup dismissal helper

    All other attributes and methods delegate to the underlying Playwright Page
    via __getattr__, so click, fill, wait_for_selector, screenshot, keyboard,
    mouse, evaluate, and similar APIs work like native Playwright calls.

    Only goto is wrapped because it is the most common popup trigger. Wrapping
    click would add avoidable delay to a high-frequency API; callers can run
    dismiss_popups() explicitly after clicks that are expected to open modals.
    """

    def __init__(self, page: Page, popup_selectors: list[str]) -> None:
        self._page = page
        self._popup_selectors = popup_selectors

    async def goto(self, url: str, **kwargs: Any) -> Any:
        response = await self._page.goto(url, **kwargs)
        try:
            await dismiss_popups(self._page, self._popup_selectors)
        except Exception as exc:  # noqa: BLE001
            logger.warning("smart_page_post_goto_dismiss_failed", url=url, error=str(exc))
        return response

    async def dismiss_popups(self) -> list[str]:
        return await dismiss_popups(self._page, self._popup_selectors)

    @property
    def raw(self) -> Page:
        """Escape hatch: get the underlying Playwright Page directly."""
        return self._page

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)


@asynccontextmanager
async def smart_browse(
    user_id: str = "default",
    domain: str = "",
    viewport: tuple[int, int] = (1280, 720),
    device_scale_factor: float = 1.0,
    ad_block_domains: list[str] | None = None,
    popup_close_selectors: list[str] | None = None,
    headless: bool = True,
    storage_state_store: StorageStateStore | None = None,
) -> AsyncIterator[SmartPage]:
    """Open a configured Playwright page for multi-step browser workflows."""
    storage_state_path = None
    try:
        if domain:
            store = storage_state_store or StorageStateStore()
            storage_state_path = store.load_state_path(user_id, domain)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "smart_browse_storage_state_lookup_failed",
            user_id=user_id,
            domain=domain,
            error=str(exc),
        )
        raise AgentError("SMART_BROWSE_STORAGE_STATE_ERROR", str(exc)) from exc

    async with BrowserSession(
        user_id,
        storage_state_path,
        headless=headless,
        device_scale_factor=device_scale_factor,
    ) as session:
        try:
            page = await session.new_page()
            width, height = viewport
            # Viewport 固定 + device_scale_factor=1 是 Phase 3b 视觉 subagent 的硬约束。
            # 截图坐标 -> click 坐标必须 1:1 对应，scale != 1 会导致点错位置。
            # 调用方可改 viewport 尺寸，但建议保持 scale=1。
            await page.set_viewport_size({"width": width, "height": height})
            await install_route_blocker(page, ad_block_domains or [])
        except Exception as exc:  # noqa: BLE001
            logger.error("smart_browse_page_setup_failed", user_id=user_id, error=str(exc))
            raise AgentError("SMART_BROWSE_PAGE_SETUP_ERROR", str(exc)) from exc
        yield SmartPage(page, popup_close_selectors or [])


__all__ = ["SmartPage", "smart_browse"]
