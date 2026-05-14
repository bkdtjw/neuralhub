from __future__ import annotations

import time

from backend.core.s02_tools.builtin.browser import SmartPage

from .login_session_models import LoginAssistResult


async def request_sms_code(page: SmartPage, phone: str) -> LoginAssistResult:
    await try_click(page, ["text=短信登录", "text=手机短信登录", "text=短信验证码登录"])
    phone_filled = await try_fill(
        page,
        [
            "input[type='tel']",
            "input[name='phone']",
            "input[name='mobile']",
            "input[placeholder*='手机号']",
            "#loginname",
            "input[name='loginname']",
        ],
        phone,
    )
    if not phone_filled:
        return LoginAssistResult(status="phone_input_missing", detail="未找到手机号输入框")
    button_clicked = await try_click(page, ["text=获取验证码", "text=发送验证码", "text=获取短信验证码"])
    if not button_clicked:
        return LoginAssistResult(status="sms_button_missing", detail="未找到发送验证码按钮")
    await page.wait_for_timeout(1500)
    text = await body_text(page)
    if has_blocked(text):
        return LoginAssistResult(status="blocked", detail=summarize(text))
    if sms_send_confirmed(text):
        return LoginAssistResult(status="sent", detail="短信验证码已请求")
    return LoginAssistResult(status="unconfirmed", detail=summarize(text) or "未确认短信验证码已发送")


async def submit_sms_code(page: SmartPage, code: str) -> None:
    await try_fill(
        page,
        [
            "input[name='authcode']",
            "input[name='code']",
            "input[placeholder*='验证码']",
            "input[type='number']",
        ],
        code,
    )
    await try_click(page, ["#loginsubmit", "text=登录", "button:has-text('登录')"])


async def submit_password(page: SmartPage, account: str, password: str) -> None:
    await try_click(page, ["text=密码登录", "text=账户登录"])
    await try_fill(page, ["#loginname", "input[name='loginname']", "input[type='text']"], account)
    await try_fill(page, ["#nloginpwd", "input[type='password']", "input[name='password']"], password)
    await try_click(page, ["#loginsubmit", "text=登录", "button:has-text('登录')"])


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


async def try_click(page: SmartPage, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            await page.click(selector, timeout=3000)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def try_fill(page: SmartPage, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            await page.fill(selector, value, timeout=3000)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def body_text(page: SmartPage) -> str:
    try:
        return await page.locator("body").inner_text(timeout=5000)
    except Exception:  # noqa: BLE001
        return ""


def has_login_success(text: str) -> bool:
    return any(marker in text for marker in ("退出", "我的京东", "购物车", "PLUS会员"))


def has_blocked(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "安全验证",
            "访问受限",
            "风控",
            "当前页面异常",
            "扫码存在风险",
            "拖动滑块",
            "图形验证码",
            "验证身份",
        )
    )


def sms_send_confirmed(text: str) -> bool:
    return any(
        marker in text
        for marker in ("验证码已发送", "发送成功", "重新获取", "重新发送", "秒后", "s后")
    )


def summarize(text: str) -> str:
    return text[:160].replace("\n", " | ")


__all__ = ["request_sms_code", "submit_password", "submit_sms_code", "wait_login_result"]
