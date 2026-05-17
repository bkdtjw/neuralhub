from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.adapters.role_router import RoleRouter
from backend.common.logging import get_logger
from backend.common.types import LLMRequest
from backend.core.s02_tools.builtin.browser import smart_browse

from .action_tools import BROWSER_ACTION_TOOLS, tool_call_to_action
from .controller import BrowserController
from .evidence import save_evidence_screenshot
from .human_gate import human_intervention_content, needs_human_intervention
from .main_agent_support import (
    SYSTEM_PROMPT_MAIN,
    decision_messages,
    last_action_kind,
    result as _result,
    should_try_login_assistant,
)
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


async def run_browser_agent(
    config: BrowserAgentConfig,
    role_router: RoleRouter,
    asset_store: AssetStore | None = None,
    login_assistant: Any | None = None,
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
            if config.initial_url:
                await controller.goto(config.initial_url)
            detector = StuckDetector(window=3)
            for step in range(config.max_steps):
                if time.monotonic() - started > config.timeout_seconds:
                    return _result(False, "timeout", step, history, screenshots)
                screenshot = await controller.take_screenshot()
                current_url = str(getattr(page, "url", ""))
                current_title = await page.title()
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
                if login_assistant and should_try_login_assistant(observation, current_url):
                    assisted = await login_assistant.assist(page, controller, observation, config)
                    if str(getattr(assisted, "status", "")) == "success":
                        continue
                if needs_human_intervention(observation, current_url):
                    await save_evidence_screenshot(asset_store, screenshots, current_url, screenshot)
                    return _result(
                        False,
                        "need_human",
                        step + 1,
                        history,
                        screenshots,
                        human_intervention_content(observation),
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
                exec_result = (
                    await save_evidence_screenshot(asset_store, screenshots, current_url, screenshot)
                    if action.kind == ActionKind.SCREENSHOT
                    else await controller.execute(action)
                )
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
                messages=decision_messages(task, history, current_url, current_title, observation),
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


def _last_action_kind(history: list[dict[str, Any]]) -> str:
    return last_action_kind(history)

__all__ = ["BROWSER_ACTION_TOOLS", "SYSTEM_PROMPT_MAIN", "main_agent_decide", "run_browser_agent"]
