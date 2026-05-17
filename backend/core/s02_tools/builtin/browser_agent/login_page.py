from __future__ import annotations

import time

from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import SmartPage

from .login_session_models import LoginAssistResult
from .login_vision import LoginVisionHelper, TargetQuery
from .login_page_probe import (
    has_blocked,
    has_login_success,
    probe_phone_input,
    sms_send_confirmed,
    summarize,
    vision_text,
)

logger = get_logger(component="browser_login_page")

SMS_LOGIN_SELECTORS = ("text=短信登录", "text=手机短信登录", "text=短信验证码登录")
PHONE_INPUT_SELECTORS = (
    "input[type='tel']", "input[name='phone']", "input[name='mobile']",
    "input[placeholder*='手机号']", "#loginname", "input[name='loginname']",
)
SMS_BUTTON_SELECTORS = ("text=获取验证码", "text=发送验证码", "text=获取短信验证码")
SMS_CODE_SELECTORS = ("input[name='authcode']", "input[name='code']", "input[placeholder*='验证码']", "input[type='number']")
PASSWORD_ACCOUNT_SELECTORS = ("#loginname", "input[name='loginname']", "input[type='text']")
PASSWORD_SELECTORS = ("#nloginpwd", "input[type='password']", "input[name='password']")
LOGIN_SUBMIT_SELECTORS = ("#loginsubmit", "text=登录", "button:has-text('登录')")


async def request_sms_code(
    page: SmartPage,
    phone: str,
    vision: LoginVisionHelper | None = None,
) -> LoginAssistResult:
    clicked_sms, sms_selector = await try_click(page, SMS_LOGIN_SELECTORS)
    _log_sms_step("open_sms_login", "clicked" if clicked_sms else "missing", "selector", sms_selector)
    if not clicked_sms and vision is not None:
        clicked = await vision.click_target(
            page,
            TargetQuery(
                question="找到短信登录、手机短信登录或验证码登录入口，并返回它的 bbox。",
                keywords=("短信", "验证码", "手机"),
            ),
        )
        _log_sms_step("open_sms_login", clicked.status, "vision", detail=clicked.detail)
        if clicked.status != "clicked":
            return clicked
    phone_filled, phone_selector = await try_fill(page, PHONE_INPUT_SELECTORS, phone)
    _log_sms_step("fill_phone", "filled" if phone_filled else "missing", "selector", phone_selector)
    if not phone_filled and vision is not None:
        typed = await vision.type_into_target(
            page,
            TargetQuery(
                question="找到手机号或手机号码输入框，并返回输入框 bbox。",
                keywords=("手机号", "手机", "号码", "输入框", "账号"),
            ),
            phone,
        )
        phone_filled = typed.status == "typed"
        _log_sms_step("fill_phone", typed.status, "vision", detail=typed.detail)
        if not phone_filled:
            return typed
    if not phone_filled:
        return LoginAssistResult(status="phone_input_missing", detail="未找到手机号输入框")
    phone_probe = await probe_phone_input(page)
    if phone_probe.available:
        _log_sms_step(
            "verify_phone",
            "filled" if phone_probe.filled else "empty",
            "dom",
            phone_probe.selector,
        )
        if not phone_probe.filled:
            return LoginAssistResult(status="phone_input_unconfirmed", detail="手机号输入框未确认写入")
    else:
        _log_sms_step("verify_phone", "unavailable", "dom", detail=phone_probe.detail)
    button_clicked, button_selector = await try_click(page, SMS_BUTTON_SELECTORS)
    _log_sms_step(
        "click_send_sms",
        "clicked" if button_clicked else "missing",
        "selector",
        button_selector,
    )
    if not button_clicked and vision is not None:
        clicked = await vision.click_target(
            page,
            TargetQuery(
                question="找到获取验证码、发送验证码或获取短信验证码按钮，并返回按钮 bbox。",
                keywords=("验证码", "获取", "发送"),
            ),
        )
        button_clicked = clicked.status == "clicked"
        _log_sms_step("click_send_sms", clicked.status, "vision", detail=clicked.detail)
        if not button_clicked:
            return clicked
    if not button_clicked:
        return LoginAssistResult(status="sms_button_missing", detail="未找到发送验证码按钮")
    await page.wait_for_timeout(1500)
    text = await body_text(page)
    if has_blocked(text):
        _log_sms_step("confirm_sms", "blocked", detail=summarize(text))
        return LoginAssistResult(status="blocked", detail=summarize(text))
    if sms_send_confirmed(text):
        _log_sms_step("confirm_sms", "sent")
        return LoginAssistResult(status="sent", detail="短信验证码已请求")
    if vision is not None:
        observation = await vision.observe_page(
            page,
            "判断短信验证码是否已经发送成功，或者是否出现滑块、安全验证、错误提示。",
        )
        visual_text = vision_text(observation)
        if has_blocked(visual_text):
            _log_sms_step("confirm_sms", "blocked", "vision", detail=summarize(visual_text))
            return LoginAssistResult(status="blocked", detail=summarize(visual_text))
        if sms_send_confirmed(visual_text):
            _log_sms_step("confirm_sms", "sent", "vision")
            return LoginAssistResult(status="sent", detail="短信验证码已请求")
        _log_sms_step("confirm_sms", "unconfirmed", "vision", detail=summarize(visual_text))
        return LoginAssistResult(status="unconfirmed", detail=summarize(visual_text))
    _log_sms_step("confirm_sms", "unconfirmed", detail=summarize(text))
    return LoginAssistResult(status="unconfirmed", detail=summarize(text) or "未确认短信验证码已发送")


async def submit_sms_code(page: SmartPage, code: str) -> None:
    await try_fill(page, SMS_CODE_SELECTORS, code)
    await try_click(page, LOGIN_SUBMIT_SELECTORS)


async def submit_password(page: SmartPage, account: str, password: str) -> None:
    await try_click(page, ("text=密码登录", "text=账户登录"))
    await try_fill(page, PASSWORD_ACCOUNT_SELECTORS, account)
    await try_fill(page, PASSWORD_SELECTORS, password)
    await try_click(page, LOGIN_SUBMIT_SELECTORS)


async def wait_login_result(page: SmartPage, timeout_seconds: float = 30.0) -> LoginAssistResult:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        text = await body_text(page)
        if has_login_success(text):
            return LoginAssistResult(status="success", detail="登录成功")
        if has_blocked(text):
            return LoginAssistResult(status="blocked", detail=summarize(text))
        await page.wait_for_timeout(2000)
    return LoginAssistResult(status="submitted", detail="已提交登录信息，等待页面确认超时")


async def try_click(page: SmartPage, selectors: tuple[str, ...]) -> tuple[bool, str]:
    for selector in selectors:
        try:
            await page.click(selector, timeout=3000)
            return True, selector
        except Exception:  # noqa: BLE001
            continue
    return False, ""


async def try_fill(page: SmartPage, selectors: tuple[str, ...], value: str) -> tuple[bool, str]:
    for selector in selectors:
        try:
            await page.fill(selector, value, timeout=3000)
            return True, selector
        except Exception:  # noqa: BLE001
            continue
    return False, ""


async def body_text(page: SmartPage) -> str:
    try:
        return await page.locator("body").inner_text(timeout=5000)
    except Exception:  # noqa: BLE001
        return ""


def _log_sms_step(step: str, status: str, method: str = "", selector: str = "", detail: str = "") -> None:
    logger.info(
        "browser_login_sms_step",
        step=step,
        status=status,
        method=method,
        selector=selector,
        detail=detail,
    )


__all__ = ["request_sms_code", "submit_password", "submit_sms_code", "wait_login_result"]
