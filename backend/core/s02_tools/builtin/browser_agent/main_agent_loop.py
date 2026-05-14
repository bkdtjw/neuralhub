from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from backend.adapters.role_router import RoleRouter
from backend.common.logging import get_logger
from backend.common.types import LLMRequest, Message
from backend.core.s02_tools.builtin.browser import smart_browse

from .action_tools import BROWSER_ACTION_TOOLS, tool_call_to_action
from .controller import BrowserController
from .models import (
    ActionKind,
    BrowserAction,
    BrowserAgentConfig,
    BrowserAgentResult,
    VisionObservation,
)
from .stuck_detector import StuckDetector
from .vision_subagent import VisionRequest, observe

if TYPE_CHECKING:
    from backend.storage.asset_store import AssetStore

logger = get_logger(component="browser_agent_loop")

SYSTEM_PROMPT_MAIN = """你是浏览器自动化主 agent。你的任务是完成用户给的高层目标。

每一步你会收到：
  - 用户原始任务
  - 截至目前的操作历史（含每步的页面摘要、动作、结果）
  - vision subagent 对当前截图的观察（页面摘要 + 可见元素 + 建议）

你必须调用一个工具作为你的下一步动作。可用工具：click_selector, click_coords,
fill, scroll, wait, wait_for_selector, goto, key, extract_text, screenshot, done, fail。

完成任务时调 done(content="..."); 无法完成时调 fail(reason="...")。
不要在 selector 里猜测——优先用 vision 的 selector_hint；没有时用坐标 click_coords。
"""


async def run_browser_agent(
    config: BrowserAgentConfig,
    role_router: RoleRouter,
    asset_store: AssetStore | None = None,
) -> BrowserAgentResult:
    history: list[dict[str, Any]] = []
    screenshots = []
    started = time.monotonic()
    try:
        async with smart_browse(
            user_id=config.user_id,
            domain=config.domain,
            viewport=config.viewport,
        ) as page:
            controller = BrowserController(page)
            detector = StuckDetector(window=3)
            for step in range(config.max_steps):
                if time.monotonic() - started > config.timeout_seconds:
                    return _result(False, "timeout", step, history, screenshots)
                screenshot = await controller.take_screenshot()
                current_url = str(getattr(page, "url", ""))
                current_title = await page.title()
                if asset_store is not None:
                    path = await asset_store.save_screenshot(
                        "browser_agent",
                        current_url,
                        screenshot,
                    )
                    screenshots.append(path)
                last_kind = _last_action_kind(history)
                if detector.is_stuck(current_url, screenshot, last_kind):
                    return _result(False, "stuck", step, history, screenshots)
                observation = await observe(
                    VisionRequest(
                        screenshot=screenshot,
                        url=current_url,
                        title=current_title,
                        viewport=config.viewport,
                        task_hint=config.task,
                        last_action_kind=last_kind,
                    ),
                    role_router,
                    config.vision_subagent_provider_id,
                )
                action = await main_agent_decide(
                    config.task,
                    history,
                    current_url,
                    current_title,
                    observation,
                    role_router,
                    config.main_agent_provider_id,
                )
                if action.kind == ActionKind.DONE:
                    return _result(True, "done", step + 1, history, screenshots, action.value)
                if action.kind == ActionKind.FAIL:
                    return _result(False, action.reason or "fail", step + 1, history, screenshots)
                exec_result = await controller.execute(action)
                history.append(
                    {
                        "step": step,
                        "url_before": current_url,
                        "observation_summary": observation.page_summary,
                        "action": action.model_dump(mode="json"),
                        "result": exec_result.model_dump(mode="json"),
                    }
                )
            return _result(False, "max_steps", config.max_steps, history, screenshots)
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_agent_loop_failed", error=str(exc))
        return _result(False, "error", len(history), history, screenshots, str(exc))


async def main_agent_decide(
    task: str,
    history: list[dict[str, Any]],
    current_url: str,
    current_title: str,
    observation: VisionObservation,
    role_router: RoleRouter,
    provider_id: str = "",
) -> BrowserAction:
    try:
        provider = await role_router.resolve_provider("text", provider_id)
        adapter = await role_router.get_adapter(provider.id)
        response = await adapter.complete(  # type: ignore[attr-defined]
            LLMRequest(
                model=provider.default_model,
                messages=_decision_messages(task, history, current_url, current_title, observation),
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


def _last_action_kind(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    action = history[-1].get("action", {})
    return str(action.get("kind", "")) if isinstance(action, dict) else ""


def _result(
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


__all__ = ["BROWSER_ACTION_TOOLS", "SYSTEM_PROMPT_MAIN", "main_agent_decide", "run_browser_agent"]
