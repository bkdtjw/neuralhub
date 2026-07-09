from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

import pytest
import pytest_asyncio

from backend.api.routes.websocket import ConnectionManager
from backend.api.routes.websocket_loop_cache import LoopCache
from backend.api.routes.websocket_support import LoopSettings
from backend.common.types import Message

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


class FakeMessageHistory:
    # has_checkpoint_fn=True 且未失败 → _sync_messages 直接返回，不触碰 store。
    has_checkpoint_fn = True
    checkpoint_failed = False


class FakeLoop:
    """替身 loop：只暴露回收路径需要的 message_history / messages / abort。"""

    def __init__(self) -> None:
        self.aborted = False
        self._history = FakeMessageHistory()

    @property
    def message_history(self) -> FakeMessageHistory:
        return self._history

    @property
    def messages(self) -> list[Message]:
        return []

    def abort(self) -> None:
        self.aborted = True


async def _sleeper() -> None:
    await asyncio.sleep(30)


def _settings() -> LoopSettings:
    return LoopSettings(model="test")


async def _running_task(manager: ConnectionManager, session_id: str) -> asyncio.Task[None]:
    task = asyncio.create_task(_sleeper())
    manager._tasks[session_id] = task  # noqa: SLF001
    await asyncio.sleep(0)  # 让任务真正进入运行态，task.done() 为 False
    return task


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


# --- disconnect 回收 ---


async def test_disconnect_pops_idle_loop() -> None:
    manager = ConnectionManager()
    loop = FakeLoop()
    await manager.store_loop("s", loop, _settings())  # type: ignore[arg-type]
    assert "s" in manager._loop_settings  # noqa: SLF001  # 前置：settings 已登记

    await manager.disconnect("s")

    assert "s" not in manager._loops  # noqa: SLF001  # 空闲断连回收 loop
    assert "s" not in manager._loop_settings  # noqa: SLF001  # settings 一并回收
    assert loop.aborted is True


async def test_disconnect_keeps_busy_loop() -> None:
    manager = ConnectionManager()
    loop = FakeLoop()
    await manager.store_loop("s", loop, _settings())  # type: ignore[arg-type]
    task = await _running_task(manager, "s")

    await manager.disconnect("s")

    assert "s" in manager._loops  # noqa: SLF001  # 有在跑任务不回收
    assert "s" in manager._loop_settings  # noqa: SLF001
    assert loop.aborted is False
    await _cancel(task)


# --- done_callback 的同步回收（_evict_if_idle） ---


async def test_evict_if_idle_recycles_only_after_disconnect() -> None:
    manager = ConnectionManager()
    loop = FakeLoop()
    await manager.store_loop("s", loop, _settings())  # type: ignore[arg-type]

    manager._connections["s"] = object()  # type: ignore[assignment]  # noqa: SLF001
    manager._evict_if_idle("s")  # noqa: SLF001  # 连接仍在 → 不回收
    assert "s" in manager._loops  # noqa: SLF001
    assert loop.aborted is False

    manager._connections.pop("s", None)  # noqa: SLF001
    manager._evict_if_idle("s")  # noqa: SLF001  # 连接已断 → 回收
    assert "s" not in manager._loops  # noqa: SLF001
    assert "s" not in manager._loop_settings  # noqa: SLF001
    assert loop.aborted is True


# --- LRU 封顶淘汰 ---


async def test_lru_evicts_oldest_idle_loop() -> None:
    manager = ConnectionManager()
    manager._loop_cache = LoopCache(manager._is_busy, max_loops=2)  # noqa: SLF001
    a, b, c = FakeLoop(), FakeLoop(), FakeLoop()

    await manager.store_loop("a", a, _settings())  # type: ignore[arg-type]
    await manager.store_loop("b", b, _settings())  # type: ignore[arg-type]
    await manager.store_loop("c", c, _settings())  # type: ignore[arg-type]  # 超限，淘汰最久未用 a

    assert "a" not in manager._loops  # noqa: SLF001
    assert a.aborted is True  # 被淘汰的 loop 会被 abort
    assert set(manager._loops.keys()) == {"b", "c"}  # noqa: SLF001
    assert set(manager._loop_settings.keys()) == {"b", "c"}  # noqa: SLF001  # settings 同步淘汰


async def test_lru_skips_running_loop_and_evicts_next_idle() -> None:
    manager = ConnectionManager()
    manager._loop_cache = LoopCache(manager._is_busy, max_loops=2)  # noqa: SLF001
    a, b, c = FakeLoop(), FakeLoop(), FakeLoop()

    await manager.store_loop("a", a, _settings())  # type: ignore[arg-type]
    task = await _running_task(manager, "a")  # a 最久未用，但有在跑任务
    await manager.store_loop("b", b, _settings())  # type: ignore[arg-type]
    await manager.store_loop("c", c, _settings())  # type: ignore[arg-type]  # 超限

    assert "a" in manager._loops  # noqa: SLF001  # 在跑任务的 loop 不被 LRU 淘汰
    assert a.aborted is False
    assert "b" not in manager._loops  # noqa: SLF001  # 次久未用且空闲的 b 被淘汰
    assert b.aborted is True
    assert "c" in manager._loops  # noqa: SLF001
    await _cancel(task)


async def test_lru_touch_on_get_protects_recently_used() -> None:
    manager = ConnectionManager()
    manager._loop_cache = LoopCache(manager._is_busy, max_loops=2)  # noqa: SLF001
    a, b, c = FakeLoop(), FakeLoop(), FakeLoop()

    await manager.store_loop("a", a, _settings())  # type: ignore[arg-type]
    await manager.store_loop("b", b, _settings())  # type: ignore[arg-type]
    assert manager.get_loop("a") is a  # 命中刷新 a 为最近使用，b 变最久未用
    await manager.store_loop("c", c, _settings())  # type: ignore[arg-type]  # 超限，应淘汰 b

    assert "b" not in manager._loops  # noqa: SLF001
    assert b.aborted is True
    assert set(manager._loops.keys()) == {"a", "c"}  # noqa: SLF001
