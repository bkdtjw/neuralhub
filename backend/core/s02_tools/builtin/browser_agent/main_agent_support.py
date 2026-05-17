from __future__ import annotations

import json
from typing import Any

from backend.common.types import Message

from .models import BrowserAgentResult, VisionObservation

SYSTEM_PROMPT_MAIN = """你是浏览器自动化主 agent。你的任务是完成用户给的高层目标。

每一步你会收到：
  - 用户原始任务
  - 截至目前的操作历史（含每步的页面摘要、动作、结果）
  - vision subagent 对当前截图的观察（页面摘要 + 可见元素 + 建议）

你必须调用一个工具作为你的下一步动作。可用工具：click_selector, click_coords,
fill, scroll, wait, wait_for_selector, goto, key, extract_text, screenshot, done, fail。

完成任务时调 done(content="..."); 无法完成时调 fail(reason="...")。
不要在 selector 里猜测——优先用 vision 的 selector_hint；没有时用坐标 click_coords。
当截图值得作为证据发送时调用 screenshot(reason="...")，例如目标结果页、价格/库存/登录/验证码/阻塞页；普通中间页不要截图。
"""


def decision_messages(
    task: str,
    history: list[dict[str, Any]],
    current_url: str,
    current_title: str,
    observation: VisionObservation,
) -> list[Message]:
    payload = {
        "task": task,
        "current_url": current_url,
        "current_title": current_title,
        "history": history,
        "vision_observation": observation.model_dump(mode="json"),
    }
    return [
        Message(role="system", content=SYSTEM_PROMPT_MAIN),
        Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]


def last_action_kind(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    action = history[-1].get("action", {})
    return str(action.get("kind", "")) if isinstance(action, dict) else ""


def should_try_login_assistant(observation: VisionObservation, current_url: str) -> bool:
    text = f"{current_url} {observation.page_summary} {observation.raw_text}".lower()
    return any(term in text for term in ("login", "passport.jd.com", "登录", "短信登录", "密码登录"))


def result(
    success: bool,
    reason: str,
    steps: int,
    history: list[dict[str, Any]],
    screenshots: list[Any],
    content: str = "",
) -> BrowserAgentResult:
    return BrowserAgentResult(
        success=success,
        reason=reason,
        content=content,
        steps_taken=steps,
        history=history,
        screenshots=screenshots,
    )


__all__ = [
    "SYSTEM_PROMPT_MAIN",
    "decision_messages",
    "last_action_kind",
    "result",
    "should_try_login_assistant",
]
