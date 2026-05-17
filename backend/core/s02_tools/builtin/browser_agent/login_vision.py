from __future__ import annotations

from pydantic import BaseModel, Field

from backend.adapters.role_router import RoleRouter
from backend.core.s02_tools.builtin.browser import SmartPage

from .login_session_models import LoginAssistResult
from .models import ElementHint, VisionObservation
from .vision_subagent import VisionRequest, observe


class TargetQuery(BaseModel):
    question: str
    keywords: tuple[str, ...] = Field(default_factory=tuple)


class LoginVisionHelper:
    """Stateless visual locator for the current login page frame."""

    def __init__(
        self,
        role_router: RoleRouter,
        provider_id: str = "",
        viewport: tuple[int, int] = (1280, 720),
    ) -> None:
        self._role_router = role_router
        self._provider_id = provider_id
        self._viewport = viewport

    async def observe_page(self, page: SmartPage, question: str) -> VisionObservation:
        title = await _safe_title(page)
        screenshot = await page.screenshot()
        return await observe(
            VisionRequest(
                screenshot=screenshot,
                url=str(getattr(page, "url", "")),
                title=title,
                viewport=self._viewport,
                task_hint=question,
            ),
            self._role_router,
            self._provider_id,
        )

    async def click_target(self, page: SmartPage, query: TargetQuery) -> LoginAssistResult:
        observation = await self.observe_page(page, query.question)
        target = _pick_target(observation, query)
        if target is None or target.bbox is None:
            return LoginAssistResult(status="vision_target_missing", detail=_detail(observation))
        x, y = _center(target.bbox, self._viewport)
        await page.mouse.click(x, y)
        await page.wait_for_timeout(700)
        return LoginAssistResult(status="clicked", detail=target.description)

    async def type_into_target(
        self,
        page: SmartPage,
        query: TargetQuery,
        value: str,
    ) -> LoginAssistResult:
        clicked = await self.click_target(page, query)
        if clicked.status != "clicked":
            return clicked
        await page.keyboard.press("Control+A")
        await page.keyboard.type(value)
        await page.wait_for_timeout(500)
        return LoginAssistResult(status="typed", detail=clicked.detail)


def _pick_target(observation: VisionObservation, query: TargetQuery) -> ElementHint | None:
    if observation.target_element is not None and observation.target_element.bbox is not None:
        if not query.keywords or _matches(observation.target_element, query.keywords):
            return observation.target_element
    candidates = [item for item in observation.visible_elements if item.bbox is not None]
    matched = [item for item in candidates if _matches(item, query.keywords)]
    if matched:
        return max(matched, key=lambda item: item.confidence)
    return observation.target_element if observation.target_element is not None else None


def _matches(element: ElementHint, keywords: tuple[str, ...]) -> bool:
    if not keywords:
        return True
    text = f"{element.description} {element.selector_hint}".lower()
    return any(keyword.lower() in text for keyword in keywords)


def _center(bbox: tuple[int, int, int, int], viewport: tuple[int, int]) -> tuple[int, int]:
    left, top, right, bottom = bbox
    width, height = viewport
    x = min(max((left + right) // 2, 0), max(width - 1, 0))
    y = min(max((top + bottom) // 2, 0), max(height - 1, 0))
    return x, y


def _detail(observation: VisionObservation) -> str:
    return (
        observation.screenshot_reason
        or observation.suggested_next_action
        or observation.page_summary
        or "视觉模型未定位到目标元素"
    )


async def _safe_title(page: SmartPage) -> str:
    try:
        return await page.title()
    except Exception:  # noqa: BLE001
        return ""


__all__ = ["LoginVisionHelper", "TargetQuery"]
