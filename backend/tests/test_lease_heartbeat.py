from __future__ import annotations

import asyncio
from time import time

import pytest

from backend.api.task_queue_consumer import _build_sub_agent_loop, _heartbeat_loop
from backend.common.types import AgentEvent, Message
from backend.config import get_redis
from backend.core.s02_tools.builtin.spawn_agent import create_spawn_agent_tool
from backend.core.s02_tools.builtin.spawn_agent_support import SpawnAgentDeps
from backend.core.task_queue import TaskQueue
from backend.core.task_queue_types import TaskStatus
from backend.storage import SessionStore, SubAgentTaskStore
from backend.storage.database import SessionFactory
from backend.tests.lease_heartbeat_support import (
    ReuseQueue,
    Runtime,
    expired_running,
    registry,
    status,
)


@pytest.fixture
def queue(db_session_factory: SessionFactory) -> TaskQueue:
    redis = get_redis()
    assert redis is not None
    return TaskQueue(
        namespace="sub_agent",
        redis_client=redis,
        task_ttl_seconds=86400,
        claim_block_seconds=1,
        persistence=SubAgentTaskStore(db_session_factory),
    )


@pytest.mark.asyncio
async def test_heartbeat_renews_running_task_lease(queue: TaskQueue) -> None:
    await queue.submit("hb-renew", {"input": "work"}, timeout_seconds=0.01)
    claimed = await queue.claim("worker-a")
    assert claimed is not None
    heartbeat = asyncio.create_task(_heartbeat_loop(queue, "hb-renew", 0.005, 0.5))
    renewed_lease = await _wait_for_lease_extension(queue, "hb-renew", claimed.lease_expires_at)
    heartbeat.cancel()
    with pytest.raises(asyncio.CancelledError):
        await heartbeat
    assert renewed_lease > claimed.lease_expires_at + 0.1


@pytest.mark.asyncio
async def test_heartbeat_stops_after_cancel_and_lease_expires(queue: TaskQueue) -> None:
    await queue.submit("hb-stop", {"input": "work"}, timeout_seconds=0.01)
    assert await queue.claim("worker-a") is not None
    initial_lease = (await status(queue, "hb-stop")).lease_expires_at
    heartbeat = asyncio.create_task(_heartbeat_loop(queue, "hb-stop", 0.005, 0.03))
    await _wait_for_lease_extension(queue, "hb-stop", initial_lease)
    heartbeat.cancel()
    with pytest.raises(asyncio.CancelledError):
        await heartbeat
    lease_after_cancel = (await status(queue, "hb-stop")).lease_expires_at
    await asyncio.sleep(0.04)
    current = await status(queue, "hb-stop")
    assert current.lease_expires_at == lease_after_cancel
    assert time() > current.lease_expires_at


@pytest.mark.asyncio
async def test_lease_guard_rejects_old_worker_after_recovery(queue: TaskQueue) -> None:
    claimed = await expired_running(queue, "guard", {"input": "work"})
    assert await queue.recover_stale_tasks() == 1
    reclaimed = await queue.claim("worker-b")
    assert reclaimed is not None
    assert reclaimed.worker_id == "worker-b"
    ok = await queue.complete("guard", {"content": "late"}, worker_id=claimed.worker_id)
    assert ok is False
    current = await status(queue, "guard")
    assert current.status == TaskStatus.RUNNING
    assert current.worker_id == "worker-b"


@pytest.mark.asyncio
async def test_recovery_with_checkpoint_restores_messages(
    queue: TaskQueue,
    db_session_factory: SessionFactory,
) -> None:
    await expired_running(queue, "recover-checkpoint", {"spec_id": "reviewer", "input": "go"})
    store = SessionStore(db_session_factory)
    await store.ensure_session("sub-agent:recover-checkpoint", model="m", provider="p")
    await store.add_messages(
        "sub-agent:recover-checkpoint",
        [Message(role="user", content="old input")],
    )
    assert await queue.recover_stale_tasks() == 1
    reclaimed = await queue.claim("worker-b")
    assert reclaimed is not None
    loop, restored = await _build_sub_agent_loop(reclaimed, Runtime())
    assert restored is True
    assert [message.content for message in loop.messages] == ["s", "old input"]


@pytest.mark.asyncio
async def test_recovery_without_checkpoint_runs_from_start(queue: TaskQueue) -> None:
    await expired_running(queue, "recover-start", {"role": "worker", "input": "go"})
    assert await queue.recover_stale_tasks() == 1
    reclaimed = await queue.claim("worker-b")
    assert reclaimed is not None
    loop, restored = await _build_sub_agent_loop(reclaimed, Runtime())
    assert restored is False
    assert loop.messages == []


@pytest.mark.asyncio
async def test_spawn_agent_reuses_completed_children() -> None:
    queue = ReuseQueue()
    events: list[AgentEvent] = []
    execute = create_spawn_agent_tool(
        SpawnAgentDeps(
            task_queue=queue,  # type: ignore[arg-type]
            spec_registry=registry(),
            workspace="/workspace",
            event_handler=events.append,
            parent_task_id="parent-1",
        )
    )[1]
    result = await execute(
        {
            "tasks": [
                {"spec_id": "code-reviewer", "input": "first"},
                {"spec_id": "code-reviewer", "input": "second"},
            ]
        }
    )
    assert result.is_error is False
    assert len(queue.submitted) == 1
    assert "old result" in result.output
    assert "new result" in result.output
    assert events[0].data["reused"] == 1


@pytest.mark.asyncio
async def test_recovery_marks_task_failed_when_retries_exhausted(queue: TaskQueue) -> None:
    await expired_running(queue, "exhausted", {"input": "work"}, max_retries=0)
    assert await queue.recover_stale_tasks() == 0
    current = await status(queue, "exhausted")
    assert current.status == TaskStatus.FAILED
    assert "重试" in current.error


async def _wait_for_lease_extension(queue: TaskQueue, task_id: str, initial: float) -> float:
    for _ in range(40):
        await asyncio.sleep(0.01)
        current = await status(queue, task_id)
        if current.lease_expires_at > initial:
            return current.lease_expires_at
    raise AssertionError("lease was not renewed")
