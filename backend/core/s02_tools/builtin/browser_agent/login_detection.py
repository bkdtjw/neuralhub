from __future__ import annotations

from .models import BrowserAgentConfig, VisionObservation


def should_assist_login(
    config: BrowserAgentConfig,
    observation: VisionObservation,
    current_url: str,
) -> bool:
    is_jd = (
        "jd.com" in config.domain
        or "京东" in config.site_guide
        or "passport.jd.com" in current_url
    )
    if not is_jd:
        return False
    text = " ".join(
        [
            current_url,
            observation.page_summary,
            observation.suggested_next_action,
            observation.screenshot_reason,
            observation.raw_text,
        ]
    )
    return any(
        marker in text
        for marker in (
            "passport.jd.com",
            "短信登录",
            "密码登录",
            "扫码存在风险",
            "验证码",
            "登录页面",
        )
    )


def site_label(config: BrowserAgentConfig) -> str:
    if "jd.com" in config.domain or "京东" in config.site_guide:
        return "京东"
    return config.domain or "网站"


__all__ = ["should_assist_login", "site_label"]
