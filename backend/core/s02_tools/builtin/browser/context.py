from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="browser_session")


class BrowserSession:
    def __init__(
        self,
        user_id: str,
        storage_state_path: Path | None = None,
        headless: bool = True,
        device_scale_factor: float = 1.0,
    ) -> None:
        self.user_id = user_id
        self.storage_state_path = storage_state_path
        self.headless = headless
        self.device_scale_factor = device_scale_factor
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def __aenter__(self) -> BrowserSession:
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            context_args: dict[str, Any] = {"device_scale_factor": self.device_scale_factor}
            if self.storage_state_path and self.storage_state_path.exists():
                context_args["storage_state"] = str(self.storage_state_path)
            self._context = await self._browser.new_context(**context_args)
            return self
        except Exception as exc:  # noqa: BLE001
            logger.error("browser_session_start_failed", user_id=self.user_id, error=str(exc))
            raise AgentError("BROWSER_SESSION_START_ERROR", str(exc)) from exc

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._browser is not None:
                await self._browser.close()
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception as close_exc:  # noqa: BLE001
            logger.error(
                "browser_session_close_failed",
                user_id=self.user_id,
                error=str(close_exc),
            )
            if exc_type is None:
                raise AgentError("BROWSER_SESSION_CLOSE_ERROR", str(close_exc)) from close_exc

    async def new_page(self) -> Any:
        try:
            if self._context is None:
                raise AgentError("BROWSER_CONTEXT_MISSING", "Browser context is not started")
            return await self._context.new_page()
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("browser_new_page_failed", user_id=self.user_id, error=str(exc))
            raise AgentError("BROWSER_NEW_PAGE_ERROR", str(exc)) from exc


__all__ = ["BrowserSession"]
