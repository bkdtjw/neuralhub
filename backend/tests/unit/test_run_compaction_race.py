from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from backend.adapters.base import LLMAdapter
from backend.common.types import (
    AgentConfig,
    LLMRequest,
    LLMResponse,
    Message,
    StreamChunk,
    ToolDefinition,
)
from backend.core.s01_agent_loop.agent_loop import AgentLoop
from backend.core.s01_agent_loop.compaction_writeback import (
    apply_layered_compaction,
    reattach_concurrent_messages,
)
from backend.core.s02_tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def bind_test_database() -> object:
    # 覆盖 conftest 里 autouse 的 Postgres 容器夹具：本文件是纯内存单测，无需起容器。
    yield


def _msg(content: str, role: str = "user") -> Message:
    return Message(role=role, content=content)


# ---------- 差量写回纯函数 ----------


def test_reattach_appends_concurrent_tail_messages() -> None:
    original = [_msg("a"), _msg("b"), _msg("c"), _msg("d")]
    snapshot_len = len(original)
    compacted = [_msg("summary-1"), _msg("summary-2")]  # 压缩把旧消息压成 2 条
    appended = [_msg("x"), _msg("y")]  # await 期间并发追加到尾部
    messages = original + appended
    result = reattach_concurrent_messages(compacted, messages, snapshot_len)
    assert [m.content for m in result] == ["summary-1", "summary-2", "x", "y"]
    assert result[-2:] == appended  # 并发追加的 2 条仍在尾部


def test_reattach_without_appends_returns_compacted_unchanged() -> None:
    original = [_msg("a"), _msg("b")]
    compacted = [_msg("s")]
    result = reattach_concurrent_messages(compacted, list(original), len(original))
    assert result == compacted


def test_reattach_dedupes_tail_already_in_compacted() -> None:
    tail = _msg("x")
    original = [_msg("a"), _msg("b")]
    messages = original + [tail]
    compacted = [_msg("a2"), tail]  # 兜底路径可能返回已含尾部的实时整表
    result = reattach_concurrent_messages(compacted, messages, len(original))
    assert result == compacted
    assert [m.id for m in result].count(tail.id) == 1  # 不重复


# ---------- apply_layered_compaction：await 期间并发追加不丢失 ----------


class _StubTokenCounter:
    def estimate_messages_tokens(self, messages: list[Message]) -> int:
        return 1

    def estimate_tools_tokens(self, tools: list[ToolDefinition]) -> int:
        return 0


class _StubPolicy:
    def __init__(self, compact: bool) -> None:
        self._compact = compact

    def should_compact(self, tokens: int) -> bool:
        return self._compact


class _StubCompressor:
    def __init__(self, policy: _StubPolicy, inject: Message | None = None) -> None:
        self.policy = policy
        self._inject = inject

    async def compact(self, messages: list[Message]) -> list[Message]:
        if self._inject is not None:
            messages.append(self._inject)  # L1 await 期间模拟并发追加
        await asyncio.sleep(0)
        return [_msg("[l1-summary]")]  # 压缩结果不含 inject


class _StubLayered:
    def __init__(self, inject_on_summarize: Message | None = None) -> None:
        self._inject = inject_on_summarize
        self.injected = False

    async def check_and_compact(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> list[Message]:
        return list(messages)

    async def summarize_and_archive(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> list[Message]:
        if self._inject is None:
            return list(messages)
        messages.append(self._inject)  # L3 await 期间模拟并发追加
        self.injected = True
        await asyncio.sleep(0)
        return [_msg("[l3-summary]")]  # 压缩结果不含 inject


class _StubLoop:
    def __init__(self, layered: _StubLayered, compressor: _StubCompressor) -> None:
        self._layered_compressor = layered
        self._compressor = compressor
        self._token_counter = _StubTokenCounter()
        self.statuses: list[str] = []

    def _set_status(self, status: str) -> None:
        self.statuses.append(status)


@pytest.mark.asyncio
async def test_apply_layered_compaction_keeps_append_during_summarize() -> None:
    injected = _msg("concurrent-append", role="assistant")
    layered = _StubLayered(inject_on_summarize=injected)
    loop = _StubLoop(layered, _StubCompressor(_StubPolicy(compact=False)))
    messages = [_msg("sys", role="system"), _msg("q")]
    await apply_layered_compaction(loop, messages, [])
    assert layered.injected is True
    assert messages[-1].id == injected.id  # 并发追加的消息仍在尾部
    assert sum(1 for m in messages if m.id == injected.id) == 1  # 未重复


@pytest.mark.asyncio
async def test_apply_layered_compaction_keeps_append_during_l1_compact() -> None:
    injected = _msg("concurrent-append", role="assistant")
    compressor = _StubCompressor(_StubPolicy(compact=True), inject=injected)
    loop = _StubLoop(_StubLayered(), compressor)
    messages = [_msg("sys", role="system"), _msg("q")]
    await apply_layered_compaction(loop, messages, [])
    assert messages[-1].id == injected.id
    assert sum(1 for m in messages if m.id == injected.id) == 1
    assert "compacting" in loop.statuses  # 确实走到了 L1 兜底压缩分支


# ---------- run 锁：串行化 + 存活/无死锁 ----------


class MockAdapter(LLMAdapter):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self._index = 0

    async def test_connection(self) -> bool:
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self._index >= len(self._responses):
            return LLMResponse(content="")
        response = self._responses[self._index]
        self._index += 1
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk(type="done")


class _SlowLayered:
    """check_and_compact 带可控延迟并记录并发度，用于验证 run 锁串行化。"""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls = 0

    async def check_and_compact(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> list[Message]:
        self.active += 1
        self.calls += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.05)  # 制造重叠窗口，无锁时两个 run 会在此交错
        finally:
            self.active -= 1
        return list(messages)

    async def summarize_and_archive(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> list[Message]:
        return list(messages)


@pytest.mark.asyncio
async def test_run_lock_serializes_concurrent_runs_on_same_loop() -> None:
    loop = AgentLoop(
        AgentConfig(model="test-model"),
        MockAdapter([LLMResponse(content="one"), LLMResponse(content="two")]),
        ToolRegistry(),
    )
    slow = _SlowLayered()
    loop._layered_compressor = slow  # 注入可控延迟压缩器
    results = await asyncio.wait_for(
        asyncio.gather(loop.run("first"), loop.run("second")),
        timeout=5.0,  # 死锁则超时失败，同时覆盖存活性
    )
    assert slow.calls == 2  # 两个 run 都真正跑完（无死锁）
    assert slow.max_active == 1  # 未交错：run 锁把同一 loop 的 run 串行化
    assert {result.content for result in results} == {"one", "two"}
