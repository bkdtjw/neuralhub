from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="browser_popup_dismisser")

COMMON_CLOSE_SELECTORS = (
    "button[aria-label='Close']",
    "button[aria-label='close']",
    "button[title='Close']",
    "[data-testid='close-button']",
    ".modal button.close",
    ".popup button.close",
    ".cookie button.accept",
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button:has-text('Got it')",
    "button:has-text('Close')",
)


async def dismiss_popups(page: Any, extra_selectors: Iterable[str] | None = None) -> list[str]:
    try:
        closed: list[str] = []
        try:
            await page.keyboard.press("Escape")
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser_escape_popup_dismiss_failed", error=str(exc))

        selectors = list(dict.fromkeys([*COMMON_CLOSE_SELECTORS, *(extra_selectors or [])]))
        for selector in selectors:
            try:
                locator = page.locator(selector)
                target = getattr(locator, "first", locator)
                await target.click(timeout=700)
                closed.append(selector)
            except Exception as exc:  # noqa: BLE001
                logger.debug("browser_popup_selector_not_closed", selector=selector, error=str(exc))
        return closed
    except Exception as exc:  # noqa: BLE001
        logger.error("browser_popup_dismiss_failed", error=str(exc))
        raise AgentError("BROWSER_POPUP_DISMISS_ERROR", str(exc)) from exc


__all__ = ["COMMON_CLOSE_SELECTORS", "dismiss_popups"]
