from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
import pytest_asyncio

from backend.core import task_queue_consumer_helpers as helpers
from backend.core.s02_tools.builtin.spawn_agent_support import PreparedTask, SpawnAgentDeps
from backend.core.s02_tools.builtin.spawn_agent_wait import wait_for_prepared_tasks
from backend.core.task_queue import TaskQueue
from backend.core.task_queue_types import TaskStatus


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存/fakeredis 单测，跳过 PostgresContainer。
    yield


@pytest.fixture
def cancel_queue(mock_redis: fakeredis.aioredis.FakeRedis) -> TaskQueue:
    return TaskQueue(
        namespace="sub_agent",
        redis_client=mock_redis,
        task_ttl_seconds=86400,
        claim_block_seconds=1,
    )


@pytest.mark.asyncio
async def test_cancel_pending_removes_from_queue_and_fails(
    cancel_queue: TaskQueue,
    mock_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await cancel_queue.submit("t-pending", {"input": "x"})

    cancelled = await cancel_queue.cancel("t-pending")

    assert cancelled is True
    # 已从队列 list 移除，brpop/lrange 都拿不到。
    assert await mock_redis.lrange(cancel_queue._queue_key, 0, -1) == []
    status = await cancel_queue.get_status("t-pending")
    assert status is not None
    assert status.status == TaskStatus.FAILED
    assert status.error == "parent_cancelled"


@pytest.mark.asyncio
async def test_cancel_running_sets_cancel_flag(cancel_queue: TaskQueue) -> None:
    await cancel_queue.submit("t-running", {"input": "y"})
    claimed = await cancel_queue.claim("worker-1")
    assert claimed is not None
    assert claimed.status == TaskStatus.RUNNING

    cancelled = await cancel_queue.cancel("t-running")

    assert cancelled is True
    assert await cancel_queue.is_cancel_requested("t-running") is True
    # RUNNING 任务只打标记，状态不变，交给 sub_worker 心跳主动中止。
    status = await cancel_queue.get_status("t-running")
    assert status is not None
    assert status.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_terminal_task_is_noop(cancel_queue: TaskQueue) -> None:
    await cancel_queue.submit("t-done", {"input": "z"})
    assert await cancel_queue.claim("worker-1") is not None
    await cancel_queue.complete("t-done", {"content": "done"})

    cancelled = await cancel_queue.cancel("t-done")

    assert cancelled is False
    assert await cancel_queue.is_cancel_requested("t-done") is False


@pytest.mark.asyncio
async def test_cancel_unknown_task_returns_false(cancel_queue: TaskQueue) -> None:
    assert await cancel_queue.cancel("missing") is False


@pytest.mark.asyncio
async def test_heartbeat_cancels_run_task_when_flag_set() -> None:
    queue = SimpleNamespace(
        renew_lease=AsyncMock(),
        is_cancel_requested=AsyncMock(return_value=True),
    )
    cancel_event = asyncio.Event()
    run_task = asyncio.ensure_future(asyncio.sleep(5))
    heartbeat = asyncio.create_task(
        helpers._heartbeat_loop(queue, "task-x", 0.01, 1.0, run_task, cancel_event)
    )

    await asyncio.wait_for(heartbeat, timeout=2.0)

    assert cancel_event.is_set()
    with pytest.raises(asyncio.CancelledError):
        await run_task
    assert run_task.cancelled()
    queue.is_cancel_requested.assert_awaited_with("task-x")


@pytest.mark.asyncio
async def test_heartbeat_keeps_running_when_flag_absent() -> None:
    queue = SimpleNamespace(
        renew_lease=AsyncMock(),
        is_cancel_requested=AsyncMock(return_value=False),
    )
    cancel_event = asyncio.Event()
    run_task = asyncio.ensure_future(asyncio.sleep(5))
    heartbeat = asyncio.create_task(
        helpers._heartbeat_loop(queue, "task-x", 0.01, 1.0, run_task, cancel_event)
    )

    await asyncio.sleep(0.05)

    assert not cancel_event.is_set()
    assert not run_task.done()
    queue.renew_lease.assert_awaited_with("task-x", 1.0)
    for pending in (heartbeat, run_task):
        pending.cancel()
        with suppress(asyncio.CancelledError):
            await pending


def _prepared(task_id: str, index: int) -> PreparedTask:
    return PreparedTask(
        index=index,
        task_id=task_id,
        label=f"label-{index}",
        timeout_seconds=5.0,
        input_data={},
    )


@pytest.mark.asyncio
async def test_wait_for_prepared_tasks_cancels_subtasks_on_cancellation() -> None:
    prepared = [_prepared("sub-1", 1), _prepared("sub-2", 2)]

    async def _hang(*_args: object, **_kwargs: object) -> list[object]:
        await asyncio.sleep(60)
        return []

    task_queue = SimpleNamespace(
        wait_for_tasks=_hang,
        get_status=AsyncMock(return_value=None),
        cancel=AsyncMock(return_value=True),
    )
    deps = SpawnAgentDeps(
        task_queue=task_queue,  # type: ignore[arg-type]
        spec_registry=SimpleNamespace(),  # type: ignore[arg-type]
        workspace="",
        event_handler=None,
        parent_task_id="parent-1",
    )

    waiting = asyncio.create_task(wait_for_prepared_tasks(prepared, deps))
    await asyncio.sleep(0.05)
    waiting.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert task_queue.cancel.await_count == 2
    cancelled_ids = {call.args[0] for call in task_queue.cancel.await_args_list}
    assert cancelled_ids == {"sub-1", "sub-2"}
