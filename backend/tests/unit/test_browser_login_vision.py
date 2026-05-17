from __future__ import annotations

import pytest

from backend.core.s02_tools.builtin.browser_agent import login_vision
from backend.core.s02_tools.builtin.browser_agent.login_vision import (
    LoginVisionHelper,
    TargetQuery,
)
from backend.core.s02_tools.builtin.browser_agent.models import ElementHint, VisionObservation


class _Mouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _Page:
    def __init__(self) -> None:
        self.mouse = _Mouse()

    async def title(self) -> str:
        return "login"

    async def screenshot(self) -> bytes:
        return b"png"

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        return None


@pytest.mark.asyncio
async def test_login_vision_helper_clicks_target_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_observe(*_args: object, **_kwargs: object) -> VisionObservation:
        return VisionObservation(
            page_summary="登录页",
            target_element=ElementHint(
                description="获取验证码按钮",
                bbox=(10, 20, 30, 40),
                confidence=0.9,
            ),
        )

    monkeypatch.setattr(login_vision, "observe", fake_observe)
    page = _Page()
    helper = LoginVisionHelper(object(), viewport=(100, 100))  # type: ignore[arg-type]

    result = await helper.click_target(
        page,  # type: ignore[arg-type]
        TargetQuery(question="找按钮", keywords=("验证码",)),
    )

    assert result.status == "clicked"
    assert page.mouse.clicks == [(20, 30)]
