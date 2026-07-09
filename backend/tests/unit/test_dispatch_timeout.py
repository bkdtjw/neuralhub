from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar, cast

import pytest
import pytest_asyncio

import backend.core.s04_sub_agents.spawner as spawner_module
from backend.common.types import ToolResult
from backend.core.s02_tools import ToolRegistry
from backend.core.s04_sub_agents.lifecycle import SubAgentLifecycle
from backend.core.s04_sub_agents.spawner import SpawnParams, SubAgentSpawner

# 工作项 C2 回归：spawn_and_run 的 CancelledError 分支必须原样重抛，
# 否则 wait_for 超时被吞成 AgentError，lifecycle 的 "timed out" 分支永不可达。


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer。
    yield


class _SleepingSpawner:
    """替身 spawner：spawn_and_run 长睡，被 cancel 时按新逻辑原样重抛。"""

    def __init__(self) -> None:
        self.cancelled = False

    async def spawn_and_run(self, params: SpawnParams) -> ToolResult:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return ToolResult(output="unreachable")  # pragma: no cover


class _BlockingLoop:
    """替身 AgentLoop：run 阻塞直到被 cancel；abort 记录调用。"""

    created: ClassVar[list["_BlockingLoop"]] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.aborted = False
        self.entered = asyncio.Event()
        _BlockingLoop.created.append(self)

    async def run(self, user_message: str) -> Any:
        self.entered.set()
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    def abort(self) -> None:
        self.aborted = True


@pytest.mark.asyncio
async def test_run_with_timeout_returns_timed_out_not_cancelled() -> None:
    spawner = _SleepingSpawner()
    lifecycle = SubAgentLifecycle(timeout=0.02)

    result = await lifecycle.run_with_timeout(cast(Any, spawner), SpawnParams(task="t"))

    assert result.is_error is True
    assert "timed out" in result.output
    assert "SUB_AGENT_CANCELLED" not in result.output
    # 子协程确实收到并原样重抛了 CancelledError（而非被吞成 AgentError）。
    assert spawner.cancelled is True


@pytest.mark.asyncio
async def test_spawn_and_run_reraises_cancelled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _BlockingLoop.created.clear()
    monkeypatch.setattr(spawner_module, "AgentLoop", _BlockingLoop)

    spawner = SubAgentSpawner(
        adapter=cast(Any, None),
        parent_registry=ToolRegistry(),
        definition_loader=cast(Any, None),
        default_model="test-model",
    )
    task = asyncio.create_task(spawner.spawn_and_run(SpawnParams(task="do work")))

    await asyncio.sleep(0)  # 让子协程推进到 await loop.run
    loop_obj = _BlockingLoop.created[0]
    await asyncio.wait_for(loop_obj.entered.wait(), timeout=1.0)

    task.cancel()
    # 断言透出的是 CancelledError 本身，而不是 AgentError("SUB_AGENT_CANCELLED")。
    with pytest.raises(asyncio.CancelledError):
        await task
    # 重抛前仍应先 abort 子 loop。
    assert loop_obj.aborted is True
