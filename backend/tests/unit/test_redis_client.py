from __future__ import annotations

import logging

import pytest

from backend.common.errors import AgentError
from backend.config import get_redis, get_redis_pubsub, init_redis
from backend.config.settings import settings

import backend.config.redis_client as redis_client

from .redis_test_support import FakeAsyncRedis, FakeRedisPool


@pytest.mark.asyncio
async def test_init_redis_raises_when_url_empty() -> None:
    settings.redis_url = ""
    await redis_client.close_redis()
    with pytest.raises(AgentError, match="REDIS_URL_MISSING"):
        await init_redis()
    assert get_redis() is None


@pytest.mark.asyncio
async def test_init_redis_raises_when_connection_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings.redis_url = "redis://nonexistent:6379/0"

    async def _fail(_: str, __: int) -> tuple[object, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(redis_client, "_create_redis_client", _fail)
    await redis_client.close_redis()
    with caplog.at_level(logging.ERROR), pytest.raises(AgentError, match="REDIS_INIT_ERROR"):
        await init_redis()
    assert get_redis() is None
    assert "redis_init_failed" in caplog.text


@pytest.mark.asyncio
async def test_get_redis_returns_client_when_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeAsyncRedis()
    fake_pool = FakeRedisPool()

    async def _create(_: str, __: int) -> tuple[FakeRedisPool, FakeAsyncRedis]:
        return fake_pool, fake_client

    monkeypatch.setattr(redis_client, "_create_redis_client", _create)
    settings.redis_url = "redis://fake:6379/0"
    await redis_client.close_redis()
    await init_redis()
    assert get_redis() is fake_client
    await redis_client.close_redis()
    assert fake_client.closed is True
    assert fake_pool.disconnected is True


@pytest.mark.asyncio
async def test_init_redis_creates_isolated_pubsub_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[int, FakeRedisPool, FakeAsyncRedis]] = []

    async def _create(_: str, max_connections: int) -> tuple[FakeRedisPool, FakeAsyncRedis]:
        pool, client = FakeRedisPool(), FakeAsyncRedis()
        created.append((max_connections, pool, client))
        return pool, client

    monkeypatch.setattr(redis_client, "_create_redis_client", _create)
    settings.redis_url = "redis://fake:6379/0"
    await redis_client.close_redis()
    await init_redis()

    # 两个池按配置上限分别创建：命令池 + pubsub 订阅池，互相隔离。
    assert [item[0] for item in created] == [
        settings.redis_max_connections,
        settings.redis_pubsub_max_connections,
    ]
    assert get_redis() is created[0][2]
    assert get_redis_pubsub() is created[1][2]
    assert get_redis() is not get_redis_pubsub()

    await redis_client.close_redis()
    assert all(client.closed for _, _, client in created)
    assert all(pool.disconnected for _, pool, _ in created)
    assert get_redis() is None
    assert get_redis_pubsub() is None


@pytest.mark.asyncio
async def test_init_redis_cleans_up_when_pubsub_pool_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_pool, command_client = FakeRedisPool(), FakeAsyncRedis()
    calls = {"count": 0}

    async def _create(_: str, __: int) -> tuple[FakeRedisPool, FakeAsyncRedis]:
        calls["count"] += 1
        if calls["count"] == 1:
            return command_pool, command_client
        raise RuntimeError("pubsub pool boom")

    monkeypatch.setattr(redis_client, "_create_redis_client", _create)
    settings.redis_url = "redis://fake:6379/0"
    await redis_client.close_redis()
    with pytest.raises(AgentError, match="REDIS_INIT_ERROR"):
        await init_redis()
    # 第二个池失败时第一个池必须被回收，不留半初始化状态。
    assert get_redis() is None
    assert get_redis_pubsub() is None
    assert command_client.closed is True
    assert command_pool.disconnected is True
