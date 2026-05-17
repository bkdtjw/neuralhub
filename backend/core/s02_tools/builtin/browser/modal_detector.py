from __future__ import annotations

from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger

logger = get_logger(component="browser_modal_detector")

_MODAL_HEURISTIC_JS = """
() => {
  const width = window.innerWidth || document.documentElement.clientWidth;
  const height = window.innerHeight || document.documentElement.clientHeight;
  const minArea = width * height * 0.35;
  for (const el of document.body.querySelectorAll('*')) {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if (!['fixed', 'sticky'].includes(style.position)) continue;
    const rect = el.getBoundingClientRect();
    const area = Math.max(0, rect.width) * Math.max(0, rect.height);
    const zIndex = Number.parseInt(style.zIndex || '0', 10);
    if (area >= minArea && zIndex >= 10) return true;
  }
  return false;
}
"""


async def has_remaining_modal(page: Any) -> bool:
    try:
        return bool(await page.evaluate(_MODAL_HEURISTIC_JS))
    except Exception as exc:  # noqa: BLE001
        logger.error("browser_modal_detection_failed", error=str(exc))
        raise AgentError("BROWSER_MODAL_DETECTION_ERROR", str(exc)) from exc


__all__ = ["has_remaining_modal"]
