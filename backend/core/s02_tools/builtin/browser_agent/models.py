from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionKind(StrEnum):
    CLICK_SELECTOR = "click_selector"
    CLICK_COORDS = "click_coords"
    FILL = "fill"
    SCROLL = "scroll"
    WAIT = "wait"
    WAIT_FOR_SELECTOR = "wait_for_selector"
    GOTO = "goto"
    KEY = "key"
    EXTRACT_TEXT = "extract_text"
    SCREENSHOT = "screenshot"
    DONE = "done"
    FAIL = "fail"


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: ActionKind
    selector: str = ""
    x: int = 0
    y: int = 0
    value: str = ""
    direction: str = ""
    amount: int = 0
    url: str = ""
    reason: str = ""


class ActionResult(BaseModel):
    success: bool
    new_url: str = ""
    extracted_text: str = ""
    error_code: str = ""
    error_detail: str = ""


class ElementHint(BaseModel):
    description: str
    selector_hint: str = ""
    bbox: tuple[int, int, int, int] | None = None
    confidence: float = 0.0


class VisionObservation(BaseModel):
    page_summary: str = ""
    visible_elements: list[ElementHint] = Field(default_factory=list)
    target_element: ElementHint | None = None
    suggested_next_action: str = ""
    screenshot_importance: float = 0.0
    task_relevance: float = 0.0
    screenshot_reason: str = ""
    confidence: float = 0.0
    need_human: bool = False
    raw_text: str = ""


class BrowserAgentConfig(BaseModel):
    task: str
    user_id: str = "default"
    domain: str = ""
    initial_url: str = ""
    site_guide: str = ""
    max_steps: int = 15
    timeout_seconds: float = 300.0
    main_agent_provider_id: str = ""
    vision_subagent_provider_id: str = ""
    viewport: tuple[int, int] = (1280, 720)


class BrowserAgentResult(BaseModel):
    success: bool
    reason: str = ""
    content: str = ""
    steps_taken: int = 0
    history: list[dict[str, Any]] = Field(default_factory=list)
    screenshots: list[Path] = Field(default_factory=list)


__all__ = [
    "ActionKind",
    "ActionResult",
    "BrowserAction",
    "BrowserAgentConfig",
    "BrowserAgentResult",
    "ElementHint",
    "VisionObservation",
]
