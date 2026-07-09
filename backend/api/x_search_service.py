from __future__ import annotations

import asyncio
import hashlib
import json

from pydantic import BaseModel

from backend.common.logging import get_logger
from backend.common.metrics import incr
from backend.common.x_budget import XBudgetError, acquire_x_call_slot
from backend.config.redis_client import get_redis
from backend.config.settings import settings
from backend.core.s02_tools.builtin.x_client import (
    XClientConfig,
    XClientError,
    XPost,
    XRateLimitError,
    XSearchOptions,
    search_x_posts,
)

logger = get_logger(component="x_search_service")

_CACHE_PREFIX = "x:search:"
# 进程内串行化真实 X 调用：单 worker 内并发请求不同时打爆同一账号（跨进程由闸门兜底）。
_call_lock = asyncio.Lock()


class XSearchServiceError(Exception):
    """X 搜索服务层错误（上游异常或序列化失败）。"""


class XSearchQuery(BaseModel):
    query: str
    days: int
    limit: int
    search_type: str


class XSearchResult(BaseModel):
    posts: list[XPost]
    rate_limited: bool = False
    retry_after: int | None = None
    cached: bool = False


def _cache_key(q: XSearchQuery) -> str:
    raw = f"{q.query}|{q.days}|{q.limit}|{q.search_type}"
    return _CACHE_PREFIX + hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def _read_cache(key: str) -> XSearchResult | None:
    redis = get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        return XSearchResult(posts=[XPost(**item) for item in data["posts"]], cached=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("x_search_cache_read_failed", error=str(exc))
        return None


async def _write_cache(key: str, posts: list[XPost]) -> None:
    redis = get_redis()
    ttl = settings.x_search_cache_ttl_seconds
    if redis is None or ttl <= 0:
        return
    try:
        payload = json.dumps({"posts": [post.model_dump() for post in posts]})
        await redis.set(key, payload, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("x_search_cache_write_failed", error=str(exc))


async def run_x_search(config: XClientConfig, query: XSearchQuery) -> XSearchResult:
    """缓存优先 → 过额度闸门 → 串行化打 X。仅在缓存未命中时消耗额度。"""
    try:
        key = _cache_key(query)
        cached = await _read_cache(key)
        if cached is not None:
            await incr("x_search_cache_hit")
            return cached
        await acquire_x_call_slot()
        async with _call_lock:
            result = await _do_search(config, query)
        if not result.rate_limited:
            await _write_cache(key, result.posts)
        await incr("x_search_calls")
        return result
    except (XBudgetError, XClientError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise XSearchServiceError(f"X 搜索服务失败：{exc}") from exc


async def _do_search(config: XClientConfig, query: XSearchQuery) -> XSearchResult:
    options = XSearchOptions(
        max_results=query.limit,
        days=query.days,
        search_type=query.search_type,
    )
    try:
        posts = await search_x_posts(query.query, config, options)
        return XSearchResult(posts=posts)
    except XRateLimitError as exc:
        # 限流：如实透传"半份结果 + 建议重试秒数"，不当作错误（内核已保留部分数据）。
        return XSearchResult(
            posts=exc.partial_posts,
            rate_limited=True,
            retry_after=exc.retry_after_seconds,
        )


__all__ = ["XSearchQuery", "XSearchResult", "XSearchServiceError", "run_x_search"]
