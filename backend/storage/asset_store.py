from __future__ import annotations

import asyncio
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from backend.common.errors import AgentError
from backend.common.logging import get_logger

if TYPE_CHECKING:
    from backend.core.s02_tools.builtin.article_extractor import Article

logger = get_logger(component="asset_store")


class AssetStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("ASSET_STORE_DIR", "reports/morning_assets"))

    async def save_screenshot(self, task_id: str, url: str, png_bytes: bytes) -> Path:
        try:
            path = self._path(task_id, "screenshots", f"{_hash_url(url)}.png")
            await asyncio.to_thread(path.write_bytes, png_bytes)
            return path
        except Exception as exc:  # noqa: BLE001
            logger.error("asset_screenshot_save_failed", task_id=task_id, url=url, error=str(exc))
            raise AgentError("ASSET_SCREENSHOT_SAVE_ERROR", str(exc)) from exc

    async def save_article(self, task_id: str, article: Article) -> Path:
        try:
            filename = f"{_safe_name(article.title or article.url)}.json"
            path = self._path(task_id, "articles", filename)
            await asyncio.to_thread(
                path.write_text,
                article.model_dump_json(indent=2),
                encoding="utf-8",
            )
            return path
        except Exception as exc:  # noqa: BLE001
            logger.error("asset_article_save_failed", task_id=task_id, error=str(exc))
            raise AgentError("ASSET_ARTICLE_SAVE_ERROR", str(exc)) from exc

    async def save_report(self, task_id: str, content: str, fmt: str = "md") -> Path:
        try:
            suffix = re.sub(r"[^a-zA-Z0-9]+", "", fmt) or "md"
            path = self._path(task_id, "reports", f"report.{suffix}")
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")
            return path
        except Exception as exc:  # noqa: BLE001
            logger.error("asset_report_save_failed", task_id=task_id, error=str(exc))
            raise AgentError("ASSET_REPORT_SAVE_ERROR", str(exc)) from exc

    def _path(self, task_id: str, kind: str, filename: str) -> Path:
        date = datetime.now().strftime("%Y-%m-%d")
        path = self.root / date / _safe_name(task_id) / kind / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())[:80]
    return safe.strip("._-") or "asset"


__all__ = ["AssetStore"]
