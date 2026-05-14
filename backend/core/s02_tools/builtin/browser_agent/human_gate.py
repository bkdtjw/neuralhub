from __future__ import annotations

from .models import VisionObservation

_HUMAN_GATE_TERMS = (
    "login",
    "sign in",
    "captcha",
    "verification",
    "verify",
    "qr",
    "二维码",
    "扫码",
    "登录",
    "验证码",
    "短信",
    "邮箱",
    "验证",
    "风控",
    "安全",
    "访问受限",
)


def needs_human_intervention(observation: VisionObservation) -> bool:
    if not observation.need_human:
        return False
    if observation.screenshot_importance >= 0.5 or observation.screenshot_reason.strip():
        return True
    return any(term in _observation_text(observation).lower() for term in _HUMAN_GATE_TERMS)


def human_intervention_content(observation: VisionObservation) -> str:
    reason = observation.screenshot_reason.strip() or observation.page_summary.strip()
    if not reason:
        reason = "当前页面需要用户处理登录、验证码、扫码或安全验证"
    return (
        "需要人工处理后继续："
        f"{reason}。我已返回当前页面截图。请在已安装 Cookie Sync 插件的本机浏览器"
        "完成登录/验证，等待同步后重新发送原任务。"
    )


def _observation_text(observation: VisionObservation) -> str:
    parts = [
        observation.page_summary,
        observation.suggested_next_action,
        observation.screenshot_reason,
        observation.raw_text,
    ]
    return " ".join(part for part in parts if part)


__all__ = ["human_intervention_content", "needs_human_intervention"]
