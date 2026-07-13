from __future__ import annotations

import asyncio
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.config.settings import settings

logger = get_logger(component="redis_client")

try:
    import redis.asyncio as redis_asyncio
except ModuleNotFoundError:
    redis_asyncio = None

_initialized_url: str | None = None
_redis_client: Any | None = None
_redis_pool: Any | None = None
# pubsub 订阅专用客户端/池：Subscriber 按 WS 会话生命周期长期独占连接，
# 与命令池隔离，防止订阅把命令池抽干导致 publish 报 MaxConnectionsError。
_pubsub_client: Any | None = None
_pubsub_pool: Any | None = None
_init_lock: asyncio.Lock | None = None


async def _create_redis_client(redis_url: str, max_connections: int) -> tuple[Any, Any]:
    if redis_asyncio is None:
        raise RuntimeError("redis package is not installed")
    pool = redis_asyncio.ConnectionPool.from_url(
        redis_url,
        max_connections=max_connections,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
        decode_responses=True,
    )
    client = redis_asyncio.Redis(connection_pool=pool)
    await client.ping()
    return pool, client


async def init_redis() -> None:
    global _initialized_url, _redis_client, _redis_pool, _pubsub_client, _pubsub_pool
    redis_url = settings.redis_url.strip()
    if _initialized_url == redis_url and _redis_client is not None:
        return
    lock = await _acquire_init_lock()
    try:
        redis_url = settings.redis_url.strip()
        if _initialized_url == redis_url and _redis_client is not None:
            return
        await _close_current()
        if not redis_url:
            raise AgentError("REDIS_URL_MISSING", "REDIS_URL must be set before initializing Redis.")
        pool: Any | None = None
        client: Any | None = None
        try:
            pool, client = await _create_redis_client(redis_url, settings.redis_max_connections)
            pubsub_pool, pubsub_client = await _create_redis_client(
                redis_url, settings.redis_pubsub_max_connections
            )
            logger.info("redis_initialized")
        except Exception as exc:
            # 第二个池创建失败时回收第一个，不留半初始化状态。
            await _close_pair(client, pool)
            _initialized_url = None
            logger.exception("redis_init_failed")
            raise AgentError("REDIS_INIT_ERROR", str(exc)) from exc
        _redis_pool = pool
        _redis_client = client
        _pubsub_pool = pubsub_pool
        _pubsub_client = pubsub_client
        _initialized_url = redis_url
    finally:
        lock.release()


def get_redis() -> Any | None:
    if settings.redis_url.strip() != (_initialized_url or ""):
        return None
    return _redis_client


def get_redis_pubsub() -> Any | None:
    # 仅供长期订阅（Subscriber）使用；普通命令一律走 get_redis()。
    if settings.redis_url.strip() != (_initialized_url or ""):
        return None
    return _pubsub_client


async def close_redis() -> None:
    global _initialized_url
    lock = await _acquire_init_lock()
    try:
        await _close_current()
        _initialized_url = None
    finally:
        lock.release()


async def _close_current() -> None:
    global _redis_client, _redis_pool, _pubsub_client, _pubsub_pool
    client = _redis_client
    pool = _redis_pool
    pubsub_client = _pubsub_client
    pubsub_pool = _pubsub_pool
    _redis_client = None
    _redis_pool = None
    _pubsub_client = None
    _pubsub_pool = None
    await _close_pair(client, pool)
    await _close_pair(pubsub_client, pubsub_pool)


async def _close_pair(client: Any | None, pool: Any | None) -> None:
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            logger.warning("redis_close_client_failed")
    if pool is not None:
        try:
            await pool.disconnect()
        except Exception:
            logger.warning("redis_close_pool_failed")


async def _acquire_init_lock() -> asyncio.Lock:
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    try:
        await _init_lock.acquire()
    except RuntimeError:
        _init_lock = asyncio.Lock()
        await _init_lock.acquire()
    return _init_lock


__all__ = ["close_redis", "get_redis", "get_redis_pubsub", "init_redis"]
