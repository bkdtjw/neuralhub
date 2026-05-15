from __future__ import annotations

from pydantic import BaseModel

from backend.core.s02_tools.builtin.browser import SmartPage

PHONE_PROBE_SELECTORS = (
    "input[type='tel']",
    "input[name='phone']",
    "input[name='mobile']",
    "input[placeholder*='手机号']",
    "#loginname",
    "input[name='loginname']",
)

PHONE_PROBE_SCRIPT = """
(selectors) => {
  for (const selector of selectors) {
    const node = document.querySelector(selector);
    if (node && "value" in node) {
      return {available: true, filled: String(node.value || "").trim().length > 0, selector};
    }
  }
  const active = document.activeElement;
  if (active && "value" in active) {
    return {available: true, filled: String(active.value || "").trim().length > 0, selector: "activeElement"};
  }
  return {available: false, filled: false, selector: ""};
}
"""


class PhoneInputProbe(BaseModel):
    available: bool = False
    filled: bool = False
    selector: str = ""
    detail: str = ""


async def probe_phone_input(page: SmartPage) -> PhoneInputProbe:
    try:
        raw = await page.evaluate(PHONE_PROBE_SCRIPT, list(PHONE_PROBE_SELECTORS))
        if isinstance(raw, dict):
            return PhoneInputProbe.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        return PhoneInputProbe(detail=type(exc).__name__)
    return PhoneInputProbe(detail="invalid_probe_result")


def has_login_success(text: str) -> bool:
    return any(marker in text for marker in ("退出", "我的京东", "购物车", "PLUS会员"))


def has_blocked(text: str) -> bool:
    normalized = text.replace(" ", "")
    for phrase in (
        "未发现安全验证",
        "未出现安全验证",
        "没有安全验证",
        "未发现滑块",
        "未出现滑块",
        "没有滑块",
        "未发现错误提示",
        "未出现错误提示",
        "没有错误提示",
        "是否出现滑块、安全验证、错误提示",
    ):
        normalized = normalized.replace(phrase, "")
    markers = ("安全验证", "访问受限", "风控", "当前页面异常", "扫码存在风险", "拖动滑块", "图形验证码", "验证身份")
    return any(marker in normalized for marker in markers)


def sms_send_confirmed(text: str) -> bool:
    return any(marker in text for marker in ("验证码已发送", "发送成功", "重新获取", "重新发送", "秒后", "s后"))


def summarize(text: str) -> str:
    return text[:160].replace("\n", " | ")


def vision_text(observation: object) -> str:
    page_summary = getattr(observation, "page_summary", "")
    next_action = getattr(observation, "suggested_next_action", "")
    target = getattr(observation, "target_element", None)
    target_text = getattr(target, "description", "") if target is not None else ""
    return " | ".join(str(part) for part in (page_summary, next_action, target_text) if part)


__all__ = [
    "PhoneInputProbe",
    "has_blocked",
    "has_login_success",
    "probe_phone_input",
    "sms_send_confirmed",
    "summarize",
    "vision_text",
]
