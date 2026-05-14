from __future__ import annotations

import pytest

from backend.core.s02_tools.builtin.browser_agent.login_page import request_sms_code


class _Locator:
    def __init__(self, text: str) -> None:
        self._text = text

    async def inner_text(self, timeout: int = 5000) -> str:
        return self._text


class _Page:
    def __init__(self, body: str, click_ok: set[str], fill_ok: set[str]) -> None:
        self.body = body
        self.click_ok = click_ok
        self.fill_ok = fill_ok
        self.filled: list[tuple[str, str]] = []

    async def click(self, selector: str, timeout: int = 3000) -> None:
        if selector not in self.click_ok:
            raise RuntimeError("missing selector")

    async def fill(self, selector: str, value: str, timeout: int = 3000) -> None:
        if selector not in self.fill_ok:
            raise RuntimeError("missing selector")
        self.filled.append((selector, value))

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        return None

    def locator(self, selector: str) -> _Locator:
        return _Locator(self.body)


@pytest.mark.asyncio
async def test_request_sms_code_requires_send_confirmation() -> None:
    page = _Page(
        body="短信验证码已发送，60秒后重新获取",
        click_ok={"text=短信登录", "text=获取验证码"},
        fill_ok={"input[type='tel']"},
    )

    result = await request_sms_code(page, "13800000000")

    assert result.status == "sent"
    assert page.filled == [("input[type='tel']", "13800000000")]


@pytest.mark.asyncio
async def test_request_sms_code_reports_missing_button() -> None:
    page = _Page(
        body="手机短信登录",
        click_ok={"text=短信登录"},
        fill_ok={"input[type='tel']"},
    )

    result = await request_sms_code(page, "13800000000")

    assert result.status == "sms_button_missing"
