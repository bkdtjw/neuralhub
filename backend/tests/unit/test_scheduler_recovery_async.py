"""D3: TaskScheduler 启动补跑改为后台任务，避免阻塞 FastAPI startup。"""
from __future__ import annotations

import asyncio
import gc
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from backend.core.s07_task_system import TaskExecutor
from backend.core.s07_task_system.scheduler import TaskScheduler


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


def _make_scheduler() -> TaskScheduler:
    store = MagicMock()
    store.list_tasks = AsyncMock(return_value=[])  # 空库：_loop 到点无任务、不触碰 Redis
    executor = MagicMock(spec=TaskExecutor)
    return TaskScheduler(store, executor, check_interval=30.0)


@pytest.mark.asyncio
async def test_start_does_not_block_on_recovery() -> None:
    """start() 必须立即返回，即使补跑协程仍在阻塞（旧代码会 await 死等）。"""
    scheduler = _make_scheduler()
    entered = asyncio.Event()
    proceed = asyncio.Event()
    completed = asyncio.Event()

    async def _blocking_recovery() -> None:
        entered.set()
        await proceed.wait()  # 迟迟不返回，模拟串行跑 LLM agent
        completed.set()

    scheduler._recover_missed_tasks = _blocking_recovery  # type: ignore[method-assign]

    # 若 start() 仍 await recovery，proceed 未 set 会死锁 → wait_for 超时判定失败。
    await asyncio.wait_for(scheduler.start(), timeout=1.0)

    # 后台任务已创建、由实例持有、且尚未完成。
    assert scheduler._recovery_task is not None
    assert not scheduler._recovery_task.done()
    assert not completed.is_set()

    # recovery 确实在后台被调度运行到了阻塞点。
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    assert not scheduler._recovery_task.done()

    # 放行让其自然结束，再干净关停。
    proceed.set()
    await asyncio.wait_for(completed.wait(), timeout=1.0)
    await scheduler.stop()


@pytest.mark.asyncio
async def test_recovery_task_held_on_instance_prevents_gc() -> None:
    """实例强引用 create_task 的返回值，任务不会被 GC 回收。"""
    scheduler = _make_scheduler()

    async def _idle_recovery() -> None:
        await asyncio.Event().wait()  # 永不完成

    scheduler._recover_missed_tasks = _idle_recovery  # type: ignore[method-assign]

    await scheduler.start()
    task_ref = scheduler._recovery_task
    assert isinstance(task_ref, asyncio.Task)

    gc.collect()  # 强制回收：实例持有强引用，任务仍存活、仍被事件循环追踪。
    assert scheduler._recovery_task is task_ref
    assert not task_ref.done()
    assert task_ref in asyncio.all_tasks()

    await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_cancels_pending_recovery() -> None:
    """stop() 取消并 await 未完成的后台补跑，优雅关停。"""
    scheduler = _make_scheduler()
    entered = asyncio.Event()

    async def _never_finishing_recovery() -> None:
        entered.set()
        await asyncio.Event().wait()  # 永不完成，模拟长时补跑

    scheduler._recover_missed_tasks = _never_finishing_recovery  # type: ignore[method-assign]

    await scheduler.start()
    recovery_task = scheduler._recovery_task
    assert recovery_task is not None
    await asyncio.wait_for(entered.wait(), timeout=1.0)

    await scheduler.stop()

    assert recovery_task.cancelled()
    assert scheduler._recovery_task is None
    assert scheduler._task is None
    assert scheduler._running is False
