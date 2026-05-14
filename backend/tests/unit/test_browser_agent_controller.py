from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.s02_tools.builtin.browser_agent.controller import BrowserController
from backend.core.s02_tools.builtin.browser_agent.models import ActionKind, BrowserAction


class FakeMouse:
    def __init__(self) -> None:
        self.click = AsyncMock()
        self.wheel = AsyncMock()


class FakeKeyboard:
    def __init__(self) -> None:
        self.press = AsyncMock()


class FakeLocator:
    def __init__(self) -> None:
        self.inner_text = AsyncMock(return_value="body text")


class FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com"
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()
        self.click = AsyncMock()
        self.fill = AsyncMock()
        self.goto = AsyncMock()
        self.wait_for_selector = AsyncMock()
        self.screenshot = AsyncMock(return_value=b"png")
        self.locator_mock = FakeLocator()

    def locator(self, selector: str) -> FakeLocator:
        self.selector = selector
        return self.locator_mock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        BrowserAction(kind=ActionKind.CLICK_SELECTOR, selector="button"),
        BrowserAction(kind=ActionKind.CLICK_COORDS, x=1, y=2),
        BrowserAction(kind=ActionKind.FILL, selector="input", value="hello"),
        BrowserAction(kind=ActionKind.SCROLL, direction="down", amount=10),
        BrowserAction(kind=ActionKind.WAIT, amount=0),
        BrowserAction(kind=ActionKind.WAIT_FOR_SELECTOR, selector="main"),
        BrowserAction(kind=ActionKind.GOTO, url="https://example.com"),
        BrowserAction(kind=ActionKind.KEY, value="Enter"),
        BrowserAction(kind=ActionKind.EXTRACT_TEXT),
        BrowserAction(kind=ActionKind.SCREENSHOT),
        BrowserAction(kind=ActionKind.DONE, value="done"),
        BrowserAction(kind=ActionKind.FAIL, reason="fail"),
    ],
)
async def test_controller_execute_all_action_kinds(action: BrowserAction) -> None:
    result = await BrowserController(FakePage()).execute(action)

    assert result.success is True


@pytest.mark.asyncio
async def test_controller_execute_returns_error_when_action_fails() -> None:
    page = FakePage()
    page.click.side_effect = RuntimeError("not clickable")

    result = await BrowserController(page).execute(
        BrowserAction(kind=ActionKind.CLICK_SELECTOR, selector="button")
    )

    assert result.success is False
    assert result.error_code
    assert "not clickable" in result.error_detail
