from __future__ import annotations

from typing import Any

from .models import BrowserAgentConfig, BrowserAgentResult, BrowserAction, VisionObservation


def last_action_kind(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    action = history[-1].get("action", {})
    return str(action.get("kind", "")) if isinstance(action, dict) else ""


def task_hint(config: BrowserAgentConfig) -> str:
    if not config.site_guide:
        return config.task
    return f"{config.task}\n\n站点说明书：\n{config.site_guide}"


def append_history(
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


__all__ = ["append_history", "last_action_kind", "result", "task_hint"]
