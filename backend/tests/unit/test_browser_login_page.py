from __future__ import annotations

import asyncio

import pytest

from backend.core.s02_tools.builtin.browser_agent import login_page
from backend.core.s02_tools.builtin.browser_agent.login_page import request_sms_code
from backend.core.s02_tools.builtin.browser_agent.login_session_models import LoginAssistResult
from backend.core.s02_tools.builtin.browser_agent.login_session import BrowserLoginSessionManager


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


class _Vision:
    def __init__(self) -> None:
        self.clicked_questions: list[str] = []
        self.typed_values: list[str] = []

    async def click_target(self, page: _Page, query: object) -> LoginAssistResult:
        self.clicked_questions.append(getattr(query, "question", ""))
        return LoginAssistResult(status="clicked", detail="视觉定位点击")

    async def type_into_target(
        self,
        page: _Page,
        query: object,
        value: str,
    ) -> LoginAssistResult:
        self.typed_values.append(value)
        return LoginAssistResult(status="typed", detail="视觉定位输入")

    async def observe_page(self, page: _Page, question: str) -> object:
        raise AssertionError("body confirmation should avoid extra vision call")


class _MissingSmsEntryVision(_Vision):
    async def click_target(self, page: _Page, query: object) -> LoginAssistResult:
        self.clicked_questions.append(getattr(query, "question", ""))
        return LoginAssistResult(status="vision_target_missing", detail="未找到短信登录入口")


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


@pytest.mark.asyncio
async def test_request_sms_code_uses_vision_for_dynamic_login_ui() -> None:
    page = _Page(
        body="短信验证码已发送，60秒后重新获取",
        click_ok={"text=短信登录"},
        fill_ok=set(),
    )
    vision = _Vision()

    result = await request_sms_code(page, "13800000000", vision)

    assert result.status == "sent"
    assert vision.typed_values == ["13800000000"]
    assert any("验证码" in question for question in vision.clicked_questions)


@pytest.mark.asyncio
async def test_request_sms_code_stops_when_sms_entry_is_not_visible() -> None:
    page = _Page(body="当前页面异常", click_ok=set(), fill_ok={"input[type='tel']"})
    vision = _MissingSmsEntryVision()

    result = await request_sms_code(page, "13800000000", vision)

    assert result.status == "vision_target_missing"
    assert vision.typed_values == []
    assert page.filled == []


@pytest.mark.asyncio
async def test_request_sms_code_emits_non_secret_step_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page(
        body="短信验证码已发送，60秒后重新获取",
        click_ok={"text=短信登录", "text=获取验证码"},
        fill_ok={"input[type='tel']"},
    )
    events: list[tuple[str, str, str, str, str]] = []

    def capture(step: str, status: str, method: str = "", selector: str = "", detail: str = "") -> None:
        events.append((step, status, method, selector, detail))

    monkeypatch.setattr(login_page, "_log_sms_step", capture)

    result = await request_sms_code(page, "13800000000")

    assert result.status == "sent"
    assert [event[0] for event in events] == [
        "open_sms_login",
        "fill_phone",
        "verify_phone",
        "click_send_sms",
        "confirm_sms",
    ]
    assert "13800000000" not in repr(events)


@pytest.mark.asyncio
async def test_login_session_stops_when_sms_request_cannot_reach_login_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BrowserLoginSessionManager()
    manager.configure(object())
    sent_cards: list[dict] = []

    async def send_card(_chat_id: str, card: dict, _session_id: str) -> None:
        sent_cards.append(card)

    async def no_login_form(*_args: object, **_kwargs: object) -> LoginAssistResult:
        return LoginAssistResult(status="vision_target_missing", detail="当前页面异常")

    monkeypatch.setattr(manager, "_send_card", send_card)
    monkeypatch.setattr(
        "backend.core.s02_tools.builtin.browser_agent.login_session.request_sms_code",
        no_login_form,
    )

    task = asyncio.create_task(manager.assist(_Page("", set(), set()), "chat", "京东"))
    await asyncio.sleep(0)
    session_id = next(iter(manager._sessions))
    await manager.submit("browser_login_sms_request", session_id, {"phone": "13800000000"})
    result = await task

    assert result.status == "vision_target_missing"
    assert len(sent_cards) == 1
