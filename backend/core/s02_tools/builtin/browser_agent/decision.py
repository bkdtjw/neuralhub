from __future__ import annotations

import json
from typing import Any

from backend.adapters.role_router import RoleRouter
from backend.common.logging import get_logger
from backend.common.types import LLMRequest, Message

from .action_tools import BROWSER_ACTION_TOOLS, tool_call_to_action
from .models import ActionKind, BrowserAction, VisionObservation

logger = get_logger(component="browser_agent_decision")

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
如果页面需要用户处理登录、扫码、验证码或安全验证，不要反复等待或重试。
"""


async def main_agent_decide(
    task: str,
    history: list[dict[str, Any]],
    current_url: str,
    current_title: str,
    observation: VisionObservation,
    role_router: RoleRouter,
    provider_id: str = "",
    site_guide: str = "",
) -> BrowserAction:
    try:
        provider = await role_router.resolve_provider("text", provider_id)
        adapter = await role_router.get_adapter(provider.id)
        response = await adapter.complete(  # type: ignore[attr-defined]
            LLMRequest(
                model=provider.default_model,
                messages=_decision_messages(
                    task,
                    history,
                    current_url,
                    current_title,
                    observation,
                    site_guide,
                ),
                tools=BROWSER_ACTION_TOOLS,
                tool_choice="any",
                temperature=0.0,
                max_tokens=2048,
            )
        )
        calls = response.tool_calls
        if len(calls) > 1:
            logger.warning("browser_agent_multiple_tool_calls", count=len(calls))
        if not calls:
            return BrowserAction(kind=ActionKind.FAIL, reason="parse_error")
        return tool_call_to_action(calls[0].name, calls[0].arguments)
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_agent_decide_failed", error=str(exc))
        return BrowserAction(kind=ActionKind.FAIL, reason="parse_error")


def _decision_messages(
    task: str,
    history: list[dict[str, Any]],
    current_url: str,
    current_title: str,
    observation: VisionObservation,
    site_guide: str = "",
) -> list[Message]:
    payload = {
        "task": task,
        "site_guide": site_guide,
        "current_url": current_url,
        "current_title": current_title,
        "history": history,
        "vision_observation": observation.model_dump(mode="json"),
    }
    return [
        Message(role="system", content=SYSTEM_PROMPT_MAIN),
        Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]


__all__ = ["BROWSER_ACTION_TOOLS", "SYSTEM_PROMPT_MAIN", "main_agent_decide"]
