from __future__ import annotations

import asyncio
import gc
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from backend.adapters.base import LLMAdapter
from backend.common.types import AgentConfig, AgentEvent, LLMRequest, LLMResponse, StreamChunk
from backend.core.s01_agent_loop import agent_loop as agent_loop_module
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s02_tools.registry import ToolRegistry


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


class _MockAdapter(LLMAdapter):
    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:  # pragma: no cover - 满足抽象签名
            yield StreamChunk(type="done")


class _RecordingLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.warnings.append((event, fields))


def _make_loop() -> AgentLoop:
    return AgentLoop(AgentConfig(model="test-model"), _MockAdapter(), ToolRegistry())


async def _drain_pending(loop: AgentLoop, ticks: int = 20) -> None:
    # 让事件任务跑完 + done 回调经 call_soon 派发执行。
    for _ in range(ticks):
        if not loop._pending_events:
            return
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_emit_records_async_handler_exception_and_clears_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop()
    recorder = _RecordingLogger()
    monkeypatch.setattr(agent_loop_module, "logger", recorder)

    async def boom(_event: AgentEvent) -> None:
        raise RuntimeError("handler boom")

    loop.on(boom)
    loop._emit("status_change", "running")
    # 派发后任务被强引用持有，防止中途被 GC 取消。
    assert len(loop._pending_events) == 1

    await _drain_pending(loop)

    assert loop._pending_events == set()
    assert len(recorder.warnings) == 1
    event_name, fields = recorder.warnings[0]
    assert event_name == "agent_event_handler_failed"
    assert "handler boom" in fields["error"]
    assert fields["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_emit_successful_handler_clears_pending_without_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop()
    recorder = _RecordingLogger()
    monkeypatch.setattr(agent_loop_module, "logger", recorder)

    seen: list[str] = []

    async def ok(event: AgentEvent) -> None:
        seen.append(event.type)

    loop.on(ok)
    loop._emit("status_change", "running")
    await _drain_pending(loop)

    assert seen == ["status_change"]
    assert loop._pending_events == set()
    assert recorder.warnings == []


@pytest.mark.asyncio
async def test_emit_cancelled_handler_task_clears_without_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop()
    recorder = _RecordingLogger()
    monkeypatch.setattr(agent_loop_module, "logger", recorder)

    started = asyncio.Event()

    async def slow(_event: AgentEvent) -> None:
        started.set()
        await asyncio.sleep(3600)

    loop.on(slow)
    loop._emit("status_change", "running")
    task = next(iter(loop._pending_events))
    await started.wait()

    task.cancel()
    await _drain_pending(loop)

    assert task.cancelled()
    assert loop._pending_events == set()
    # 取消不是失败，不应记录 warning。
    assert recorder.warnings == []


@pytest.mark.asyncio
async def test_emit_retrieves_exception_no_never_retrieved_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _make_loop()
    recorder = _RecordingLogger()
    monkeypatch.setattr(agent_loop_module, "logger", recorder)

    async def boom(_event: AgentEvent) -> None:
        raise RuntimeError("boom")

    loop.on(boom)

    handled: list[dict[str, Any]] = []
    running_loop = asyncio.get_running_loop()
    running_loop.set_exception_handler(lambda _lp, context: handled.append(context))

    loop._emit("status_change", "running")
    await _drain_pending(loop)
    assert loop._pending_events == set()

    # 任务已无强引用；强制回收后不应触发 "never retrieved"，因异常已被检索。
    gc.collect()
    await asyncio.sleep(0)

    messages = [str(context.get("message", "")) for context in handled]
    assert not any("never retrieved" in message for message in messages)
    assert any(event == "agent_event_handler_failed" for event, _ in recorder.warnings)
