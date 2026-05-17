from __future__ import annotations

import asyncio

from backend.common.errors import AgentError
from backend.core.s02_tools.builtin.browser import SmartPage

from .models import ActionKind, ActionResult, BrowserAction


class BrowserController:
    def __init__(self, page: SmartPage) -> None:
        self._page = page

    async def execute(self, action: BrowserAction) -> ActionResult:
        try:
            if action.kind == ActionKind.CLICK_SELECTOR:
                return await self.click_selector(action.selector)
            if action.kind == ActionKind.CLICK_COORDS:
                return await self.click_coords(action.x, action.y)
            if action.kind == ActionKind.FILL:
                return await self.fill(action.selector, action.value)
            if action.kind == ActionKind.SCROLL:
                return await self.scroll(action.direction, action.amount)
            if action.kind == ActionKind.WAIT:
                return await self.wait(action.amount)
            if action.kind == ActionKind.WAIT_FOR_SELECTOR:
                return await self.wait_for_selector(action.selector, action.amount or 5000)
            if action.kind == ActionKind.GOTO:
                return await self.goto(action.url)
            if action.kind == ActionKind.KEY:
                return await self.key(action.value)
            if action.kind == ActionKind.EXTRACT_TEXT:
                return await self.extract_text(action.selector)
            if action.kind == ActionKind.SCREENSHOT:
                await self.take_screenshot()
                return self._ok()
            if action.kind in {ActionKind.DONE, ActionKind.FAIL}:
                return self._ok()
            return self._error(action.kind.value, "unsupported action")
        except Exception as exc:  # noqa: BLE001
            return self._error(action.kind.value, str(exc))

    async def click_selector(self, selector: str) -> ActionResult:
        try:
            await self._page.click(selector)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.CLICK_SELECTOR.value, str(exc))

    async def click_coords(self, x: int, y: int) -> ActionResult:
        try:
            await self._page.mouse.click(x, y)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.CLICK_COORDS.value, str(exc))

    async def fill(self, selector: str, value: str) -> ActionResult:
        try:
            await self._page.fill(selector, value)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.FILL.value, str(exc))

    async def scroll(self, direction: str, amount: int) -> ActionResult:
        try:
            dx, dy = _scroll_delta(direction, amount or 600)
            await self._page.mouse.wheel(dx, dy)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.SCROLL.value, str(exc))

    async def wait(self, seconds: int) -> ActionResult:
        try:
            await asyncio.sleep(max(seconds, 0))
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.WAIT.value, str(exc))

    async def wait_for_selector(self, selector: str, timeout_ms: int = 5000) -> ActionResult:
        try:
            await self._page.wait_for_selector(selector, timeout=timeout_ms)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.WAIT_FOR_SELECTOR.value, str(exc))

    async def goto(self, url: str) -> ActionResult:
        try:
            await self._page.goto(url)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.GOTO.value, str(exc))

    async def key(self, key: str) -> ActionResult:
        try:
            await self._page.keyboard.press(key)
            return self._ok()
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.KEY.value, str(exc))

    async def extract_text(self, selector: str = "") -> ActionResult:
        try:
            target = self._page.locator(selector or "body")
            text = await target.inner_text(timeout=5000)
            return self._ok(extracted_text=text)
        except Exception as exc:  # noqa: BLE001
            return self._error(ActionKind.EXTRACT_TEXT.value, str(exc))

    async def take_screenshot(self) -> bytes:
        try:
            return await self._page.screenshot()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("BROWSER_SCREENSHOT_ERROR", str(exc)) from exc

    def _ok(self, extracted_text: str = "") -> ActionResult:
        return ActionResult(
            success=True,
            new_url=str(getattr(self._page, "url", "")),
            extracted_text=extracted_text,
        )

    @staticmethod
    def _error(kind: str, detail: str) -> ActionResult:
        return ActionResult(
            success=False,
            error_code=f"BROWSER_ACTION_{kind.upper()}_ERROR",
            error_detail=detail,
        )


def _scroll_delta(direction: str, amount: int) -> tuple[int, int]:
    clean = direction.strip().lower()
    if clean == "up":
        return 0, -amount
    if clean == "left":
        return -amount, 0
    if clean == "right":
        return amount, 0
    return 0, amount


__all__ = ["BrowserController"]
