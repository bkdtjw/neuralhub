from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from backend.config.settings import settings

class FakePubSub:
    def __init__(self, redis: FakeAsyncRedis) -> None:
        self._redis = redis
        self._channels: set[str] = set()
        self._messages: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        for channel in channels:
            self._redis.subscribers.setdefault(channel, set()).add(self)
            self._channels.add(channel)

    async def unsubscribe(self, *channels: str) -> None:
        targets = set(channels) if channels else set(self._channels)
        for channel in targets:
            self._redis.subscribers.get(channel, set()).discard(self)
            self._channels.discard(channel)

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 0.0,
    ) -> dict[str, str] | None:
        del ignore_subscribe_messages
        try:
            if timeout > 0:
                return await asyncio.wait_for(self._messages.get(), timeout=timeout)
            return self._messages.get_nowait()
        except (TimeoutError, asyncio.QueueEmpty):
            return None

    async def aclose(self) -> None:
        self.closed = True
        await self.unsubscribe()

    async def push(self, channel: str, message: str) -> None:
        await self._messages.put({"type": "message", "channel": channel, "data": message})

class FakeAsyncRedis:
    def __init__(self) -> None:
        self.closed = False
        self.fail_operations: set[str] = set()
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}
        self.list_conditions: dict[str, asyncio.Condition] = {}
        self.subscribers: dict[str, set[FakePubSub]] = {}

    async def ping(self) -> bool:
        self._maybe_fail("ping")
        return True

    async def set(self, name: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        self._maybe_fail("set")
        if nx and self._has_key(name):
            return False
        self.values[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True

    async def get(self, name: str) -> str | None:
        self._maybe_fail("get")
        return self.values.get(name)

    async def incrby(self, name: str, amount: int) -> int:
        self._maybe_fail("incrby")
        current = int(self.values.get(name, "0") or "0")
        current += amount
        self.values[name] = str(current)
        return current

    async def delete(self, name: str) -> int:
        self._maybe_fail("delete")
        existed = self._has_key(name)
        self.values.pop(name, None)
        self.lists.pop(name, None)
        self.sets.pop(name, None)
        self.ttls.pop(name, None)
        return int(existed)

    async def exists(self, name: str) -> int:
        self._maybe_fail("exists")
        return int(self._has_key(name))

    async def ttl(self, name: str) -> int:
        self._maybe_fail("ttl")
        if not self._has_key(name):
            return -2
        return self.ttls.get(name, -1)

    async def expire(self, name: str, seconds: int) -> bool:
        self._maybe_fail("expire")
        if not self._has_key(name):
            return False
        self.ttls[name] = seconds
        return True

    async def lpush(self, name: str, *values: str) -> int:
        self._maybe_fail("lpush")
        condition = self._condition(name)
        async with condition:
            items = self.lists.setdefault(name, [])
            for value in values:
                items.insert(0, value)
            condition.notify_all()
            return len(items)

    async def lrange(self, name: str, start: int, end: int) -> list[str]:
        self._maybe_fail("lrange")
        items = self.lists.get(name, [])
        stop = None if end == -1 else end + 1
        return list(items[start:stop])

    async def ltrim(self, name: str, start: int, end: int) -> bool:
        self._maybe_fail("ltrim")
        items = self.lists.get(name, [])
        stop = None if end == -1 else end + 1
        self.lists[name] = list(items[start:stop])
        return True

    async def brpop(self, name: str, timeout: int = 0) -> tuple[str, str] | None:
        self._maybe_fail("brpop")
        condition = self._condition(name)
        async with condition:
            if not self.lists.get(name):
                try:
                    await asyncio.wait_for(condition.wait(), timeout=timeout)
                except TimeoutError:
                    return None
            if not self.lists.get(name):
                return None
            value = self.lists[name].pop()
            return name, value

    async def sadd(self, name: str, *values: str) -> int:
        self._maybe_fail("sadd")
        items = self.sets.setdefault(name, set())
        before = len(items)
        items.update(values)
        return len(items) - before

    async def smembers(self, name: str) -> set[str]:
        self._maybe_fail("smembers")
        return set(self.sets.get(name, set()))

    async def srem(self, name: str, *values: str) -> int:
        self._maybe_fail("srem")
        items = self.sets.setdefault(name, set())
        removed = 0
        for value in values:
            if value in items:
                items.remove(value)
                removed += 1
        return removed

    async def publish(self, channel: str, message: str) -> int:
        self._maybe_fail("publish")
        listeners = list(self.subscribers.get(channel, set()))
        for listener in listeners:
            await listener.push(channel, message)
        return len(listeners)

    def pubsub(self) -> FakePubSub:
        self._maybe_fail("pubsub")
        return FakePubSub(self)

    async def aclose(self) -> None:
        self.closed = True

    def _condition(self, name: str) -> asyncio.Condition:
        if name not in self.list_conditions:
            self.list_conditions[name] = asyncio.Condition()
        return self.list_conditions[name]

    def _has_key(self, name: str) -> bool:
        return name in self.values or name in self.lists or name in self.sets

    def _maybe_fail(self, operation: str) -> None:
        if operation in self.fail_operations:
            raise RuntimeError(f"{operation} failed")

class FakeRedisPool:
    def __init__(self) -> None:
        self.disconnected = False
    async def disconnect(self) -> None:
        self.disconnected = True


@dataclass
class FakeRedisConnection:
    client: FakeAsyncRedis = field(default_factory=FakeAsyncRedis)
    pool: FakeRedisPool = field(default_factory=FakeRedisPool)

async def use_fake_redis(monkeypatch: Any, url: str = "redis://fake:6379/0") -> FakeRedisConnection:
    import backend.config.redis_client as redis_client

    fake = FakeRedisConnection()

    # init_redis 会调两次（命令池 + pubsub 池），复用同一个 fake 客户端，
    # 模拟同一台 Redis server 被两个池访问，保住 publish→subscribe round-trip 语义。
    async def _create_redis_client(_: str, __: int) -> tuple[FakeRedisPool, FakeAsyncRedis]:
        return fake.pool, fake.client

    monkeypatch.setattr(redis_client, "_create_redis_client", _create_redis_client)
    settings.redis_url = url
    await redis_client.close_redis()
    await redis_client.init_redis()
    return fake


__all__ = ["FakeAsyncRedis", "FakePubSub", "FakeRedisConnection", "FakeRedisPool", "use_fake_redis"]
