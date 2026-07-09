from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from backend.core import task_queue_consumer_helpers as helpers
from backend.core.task_queue import TaskPayload
from backend.core.task_queue_consumer import SubAgentConsumerContext, execute_sub_agent_task


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


def _payload(
    *,
    task_id: str = "kb-task",
    kind: str = "knowledge_ingest_local_batch",
    timeout_seconds: float = 3600.0,
) -> TaskPayload:
    # input_data 故意不含 timeout_seconds：helpers._timeout_seconds 会对其恒返回 120。
    return TaskPayload(
        task_id=task_id,
        namespace="sub_agent",
        input_data={"kind": kind},
        created_at=0.0,
        timeout_seconds=timeout_seconds,
    )


def _context(renew_lease: AsyncMock) -> Any:
    return SimpleNamespace(queue=SimpleNamespace(renew_lease=renew_lease))


@pytest.mark.asyncio
async def test_run_with_heartbeat_renews_lease_during_execution_and_cancels_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(helpers, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(helpers, "LEASE_EXTENSION_SECONDS", 60.0)
    renew_lease = AsyncMock()
    payload = _payload(task_id="kb-hb")

    async def _slow_ingest() -> str:
        await asyncio.sleep(0.06)  # 覆盖多个心跳周期
        return "done"

    await helpers._run_with_heartbeat(
        _context(renew_lease), payload, _slow_ingest, payload.timeout_seconds
    )

    # 执行期间心跳周期性续约 lease
    assert renew_lease.await_count >= 2
    for call in renew_lease.await_args_list:
        assert call.args == ("kb-hb", 60.0)
    # 任务结束后心跳被 cancel：续约计数不再增长
    count_after_return = renew_lease.await_count
    await asyncio.sleep(0.04)
    assert renew_lease.await_count == count_after_return


@pytest.mark.asyncio
async def test_execute_knowledge_task_uses_payload_timeout_not_default_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_with_heartbeat(
        context: Any,
        payload: TaskPayload,
        coro_factory: Callable[[], Awaitable[Any]],
        timeout_seconds: float,
    ) -> None:
        captured["timeout"] = timeout_seconds
        captured["kind"] = payload.input_data.get("kind")

    monkeypatch.setattr(helpers, "_run_with_heartbeat", _fake_run_with_heartbeat)
    payload = _payload(timeout_seconds=3600.0)
    context = SubAgentConsumerContext(queue=AsyncMock(), runtime=AsyncMock())

    await execute_sub_agent_task(payload, context)

    # 误用 helpers._timeout_seconds(input_data) 会得到 120（bug）；正确应取 payload.timeout_seconds。
    assert helpers._timeout_seconds(payload.input_data) == 120.0
    assert captured["timeout"] == 3600.0
    assert captured["timeout"] != 120.0
    assert captured["kind"] == "knowledge_ingest_local_batch"


@pytest.mark.asyncio
async def test_run_with_heartbeat_enforces_timeout_cap_and_cleans_up() -> None:
    renew_lease = AsyncMock()
    payload = _payload(task_id="kb-timeout", timeout_seconds=0.02)

    async def _hung_ingest() -> None:
        await asyncio.sleep(1.0)

    with pytest.raises(TimeoutError):
        await helpers._run_with_heartbeat(
            _context(renew_lease), payload, _hung_ingest, payload.timeout_seconds
        )

    # 超时上限取自传入的 payload.timeout_seconds（0.02s），而非默认 120；心跳在 finally 中被清理。
    count_after_raise = renew_lease.await_count
    await asyncio.sleep(0.03)
    assert renew_lease.await_count == count_after_raise
