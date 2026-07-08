from __future__ import annotations

from time import time

import pytest

import backend.core.task_queue_recover_support as task_queue_recover_support
from backend.config import get_redis
from backend.core.task_queue import TaskQueue
from backend.core.task_queue_types import TaskPayload, TaskStatus
from backend.storage.sub_agent_task_store import SubAgentTaskStore

from .storage_test_support import make_test_session_factory


def _payload(
    task_id: str,
    status: TaskStatus,
    lease_expires_at: float,
    *,
    retry_count: int = 0,
    max_retries: int = 1,
) -> TaskPayload:
    reference = time()
    return TaskPayload(
        task_id=task_id,
        namespace="sub_agent",
        input_data={"prompt": task_id},
        status=status,
        worker_id="worker-a",
        created_at=reference - 100,
        started_at=reference - 100,
        timeout_seconds=1.0,
        lease_expires_at=lease_expires_at,
        retry_count=retry_count,
        max_retries=max_retries,
    )


class RecordingPersistence:
    """内存持久层：记录 recover 走了哪条查询路径，避免真库依赖。"""

    def __init__(self, payloads: list[TaskPayload]) -> None:
        self.store: dict[str, TaskPayload] = {payload.task_id: payload for payload in payloads}
        self.calls: list[str] = []

    async def list_stale_running(self, now: float) -> list[TaskPayload]:
        self.calls.append("list_stale_running")
        return [
            payload
            for payload in self.store.values()
            if payload.status == TaskStatus.RUNNING and 0 < payload.lease_expires_at < now
        ]

    async def list_task_ids(self) -> list[str]:
        self.calls.append("list_task_ids")
        return list(self.store)

    async def get_status(self, task_id: str) -> TaskPayload | None:
        return self.store.get(task_id)

    async def save_payload(self, payload: TaskPayload) -> None:
        self.store[payload.task_id] = payload

    async def fail(self, task_id: str, error: str, worker_id: str = "") -> bool:
        payload = self.store.get(task_id)
        if payload is None:
            return False
        self.store[task_id] = payload.model_copy(update={"status": TaskStatus.FAILED, "error": error})
        return True

    async def has_checkpoint(self, task_id: str) -> bool:
        return False


class FakeLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def debug(self, event: str, **payload: object) -> None:
        self.calls.append(("debug", event, payload))

    def info(self, event: str, **payload: object) -> None:
        self.calls.append(("info", event, payload))

    def warning(self, event: str, **payload: object) -> None:
        self.calls.append(("warning", event, payload))


def _queue(persistence: RecordingPersistence) -> TaskQueue:
    redis = get_redis()
    assert redis is not None
    return TaskQueue(
        namespace="sub_agent",
        redis_client=redis,
        task_ttl_seconds=86400,
        claim_block_seconds=1,
        persistence=persistence,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_list_stale_running_returns_only_expired_running(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "recover_stale_running")
    store = SubAgentTaskStore(factory)
    now = time()
    try:
        await store.save_payload(_payload("expired-running", TaskStatus.RUNNING, now - 10))
        await store.save_payload(_payload("fresh-running", TaskStatus.RUNNING, now + 100))
        await store.save_payload(_payload("unleased-running", TaskStatus.RUNNING, 0.0))
        await store.save_payload(_payload("expired-succeeded", TaskStatus.SUCCEEDED, now - 10))

        stale = await store.list_stale_running(now)

        assert [payload.task_id for payload in stale] == ["expired-running"]
        assert stale[0].status == TaskStatus.RUNNING
        assert 0 < stale[0].lease_expires_at < now
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recover_uses_list_stale_running_not_full_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = time()
    persistence = RecordingPersistence(
        [
            _payload("stale-recover", TaskStatus.RUNNING, now - 5, retry_count=0, max_retries=1),
            _payload("fresh-running", TaskStatus.RUNNING, now + 100),
            _payload("done", TaskStatus.SUCCEEDED, now - 5),
        ]
    )
    fake_logger = FakeLogger()
    monkeypatch.setattr(task_queue_recover_support, "logger", fake_logger)
    queue = _queue(persistence)

    recovered = await queue.recover_stale_tasks()

    assert recovered == 1
    # 只走了单条过滤查询，没有全表扫描 + N+1。
    assert "list_stale_running" in persistence.calls
    assert "list_task_ids" not in persistence.calls
    requeued = persistence.store["stale-recover"]
    assert requeued.status == TaskStatus.PENDING
    assert requeued.retry_count == 1
    queued = await get_redis().lrange("task:sub_agent:queue", 0, -1)
    assert queued == ["stale-recover"]
    # checked 语义已从“扫描总数(3)”变为“过期任务数(1)”。
    scan = [call for call in fake_logger.calls if call[1] == "stale_task_scan"]
    assert scan == [("info", "stale_task_scan", {"namespace": "sub_agent", "checked": 1, "recovered": 1, "failed": 0})]


@pytest.mark.asyncio
async def test_recover_expires_stale_task_when_retries_exhausted() -> None:
    now = time()
    persistence = RecordingPersistence(
        [_payload("exhausted", TaskStatus.RUNNING, now - 5, retry_count=0, max_retries=0)]
    )
    queue = _queue(persistence)

    recovered = await queue.recover_stale_tasks()

    assert recovered == 0
    assert "list_stale_running" in persistence.calls
    assert "list_task_ids" not in persistence.calls
    assert persistence.store["exhausted"].status == TaskStatus.FAILED
