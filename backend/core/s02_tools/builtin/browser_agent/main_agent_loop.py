from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.adapters.role_router import RoleRouter
from backend.common.logging import get_logger
from backend.core.s02_tools.builtin.browser import smart_browse

from .action_tools import BROWSER_ACTION_TOOLS
from .controller import BrowserController
from .decision import SYSTEM_PROMPT_MAIN, main_agent_decide
from .evidence import save_evidence_screenshot
from .human_gate import human_intervention_content, needs_human_intervention
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
            if config.initial_url:
                await controller.goto(config.initial_url)
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
                        task_hint=_task_hint(config),
                        last_action_kind=last_kind,
                    ),
                    role_router,
                    config.vision_subagent_provider_id,
                )
                if needs_human_intervention(observation):
                    action = BrowserAction(
                        kind=ActionKind.SCREENSHOT,
                        reason=observation.screenshot_reason or "need_human",
                    )
                    exec_result = await save_evidence_screenshot(
                        asset_store, screenshots, current_url, screenshot
                    )
                    _append_history(history, step, current_url, observation, action, exec_result)
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
                    config.site_guide,
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
                _append_history(history, step, current_url, observation, action, exec_result)
            return _result(False, "max_steps", config.max_steps, history, screenshots)
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_agent_loop_failed", error=str(exc))
        return _result(False, "error", len(history), history, screenshots, str(exc))


def _last_action_kind(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    action = history[-1].get("action", {})
    return str(action.get("kind", "")) if isinstance(action, dict) else ""


def _task_hint(config: BrowserAgentConfig) -> str:
    if not config.site_guide:
        return config.task
    return f"{config.task}\n\n站点说明书：\n{config.site_guide}"


def _append_history(
    history: list[dict[str, Any]],
    step: int,
    current_url: str,
    observation: VisionObservation,
    action: BrowserAction,
    exec_result: Any,
) -> None:
    history.append(
        {
            "step": step,
            "url_before": current_url,
            "observation_summary": observation.page_summary,
            "action": action.model_dump(mode="json"),
            "result": exec_result.model_dump(mode="json"),
        }
    )


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
