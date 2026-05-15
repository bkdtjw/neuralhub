from __future__ import annotations

import pytest

from backend.core.s02_tools.builtin.browser_agent.login_page_probe import (
    has_blocked,
    probe_phone_input,
)


class _EvalPage:
    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw

    async def evaluate(self, script: str, selectors: list[str]) -> dict[str, object]:
        return self.raw


@pytest.mark.asyncio
async def test_probe_phone_input_reports_filled_without_value() -> None:
    result = await probe_phone_input(
        _EvalPage({"available": True, "filled": True, "selector": "input[type='tel']"})
    )

    assert result.available is True
    assert result.filled is True
    assert result.selector == "input[type='tel']"


def test_has_blocked_ignores_negative_vision_phrasing() -> None:
    text = "当前未发现安全验证或错误提示，但获取验证码按钮未处于倒计时状态"

    assert has_blocked(text) is False
    assert has_blocked("当前页面异常，请刷新或切换账户试试") is True
