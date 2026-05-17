from __future__ import annotations

import json

from backend.common.errors import AgentError
from backend.common.logging import get_logger

from .models import Article

logger = get_logger(component="article_trafilatura")


async def extract_with_trafilatura(html: str, url: str) -> Article | None:
    try:
        try:
            import trafilatura
        except ImportError:
            logger.warning("trafilatura_not_installed")
            return None

        raw = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            include_images=True,
        )
        if not raw:
            return None
        data = json.loads(raw)
        title = str(data.get("title") or "").strip()
        body = str(data.get("text") or "").strip()
        if not title and not body:
            return None
        return Article(url=url, title=title, body=body, source="trafilatura")
    except Exception as exc:  # noqa: BLE001
        logger.error("trafilatura_extract_failed", url=url, error=str(exc))
        raise AgentError("TRAFILATURA_EXTRACT_ERROR", str(exc)) from exc


__all__ = ["extract_with_trafilatura"]
