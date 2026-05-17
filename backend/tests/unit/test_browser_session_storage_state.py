from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools.builtin.browser.context import BrowserSession


class FakePlaywrightStarter:
    def __init__(self, playwright: object) -> None:
        self._playwright = playwright

    async def start(self) -> object:
        return self._playwright


@pytest.mark.asyncio
async def test_browser_session_persists_storage_state_on_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = AsyncMock()
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    playwright = AsyncMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: FakePlaywrightStarter(playwright),
    )
    state_path = tmp_path / "u1" / "example.com" / "storage_state.json"

    async with BrowserSession("u1", state_path):
        pass

    browser.new_context.assert_awaited_once_with(device_scale_factor=1.0)
    context.storage_state.assert_awaited_once_with(path=str(state_path))
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
