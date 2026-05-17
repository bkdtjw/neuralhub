from __future__ import annotations

import asyncio
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger

from ..models import Article

logger = get_logger(component="rss_adapter")


async def fetch_rss_article(feed_url: str, target_url: str) -> Article | None:
    try:
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser_not_installed")
            return None
        feed = await asyncio.to_thread(feedparser.parse, feed_url)
        for entry in getattr(feed, "entries", []):
            link = str(_entry_get(entry, "link"))
            if link and link.rstrip("/") == target_url.rstrip("/"):
                title = str(_entry_get(entry, "title"))
                body = str(_entry_get(entry, "summary") or _entry_get(entry, "description"))
                return Article(url=target_url, title=title, body=body, source="rss")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("rss_fetch_failed", feed_url=feed_url, target_url=target_url, error=str(exc))
        raise AgentError("RSS_FETCH_ERROR", str(exc)) from exc


def _entry_get(entry: Any, key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, "")
    return getattr(entry, key, "")


__all__ = ["fetch_rss_article"]
