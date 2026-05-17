from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import ActionResult

if TYPE_CHECKING:
    from backend.storage.asset_store import AssetStore


async def save_evidence_screenshot(
    asset_store: AssetStore | None,
    screenshots: list[Path],
    url: str,
    png_bytes: bytes,
) -> ActionResult:
    try:
        if asset_store is not None:
            screenshots.append(await asset_store.save_screenshot("browser_agent", url, png_bytes))
        return ActionResult(success=True, new_url=url)
    except Exception as exc:  # noqa: BLE001
        return ActionResult(
            success=False,
            new_url=url,
            error_code="BROWSER_EVIDENCE_SCREENSHOT_ERROR",
            error_detail=str(exc),
        )


__all__ = ["save_evidence_screenshot"]
