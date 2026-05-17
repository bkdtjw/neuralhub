from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from backend.common.errors import AgentError
from backend.common.logging import get_logger

from ..models import Article

logger = get_logger(component="hn_adapter")
_HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


async def fetch_hn_article(url: str) -> Article | None:
    try:
        item_id = _extract_item_id(url)
        if not item_id:
            return None
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.get(_HN_ITEM_URL.format(item_id=item_id))
            data = response.json()
        if not isinstance(data, dict):
            return None
        title = str(data.get("title") or "")
        body = str(data.get("text") or data.get("url") or "")
        return Article(url=url, title=title, body=body, source="hn_api") if title or body else None
    except Exception as exc:  # noqa: BLE001
        logger.error("hn_fetch_failed", url=url, error=str(exc))
        raise AgentError("HN_FETCH_ERROR", str(exc)) from exc


def _extract_item_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query.get("id", [""])[0]


__all__ = ["fetch_hn_article"]
