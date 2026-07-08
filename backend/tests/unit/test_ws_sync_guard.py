from __future__ import annotations

import pytest

from backend.api.routes.websocket import ConnectionManager
from backend.common.types import Message

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def bind_test_database() -> object:
    # 覆盖 conftest 里 autouse 的 Postgres 容器夹具：本文件是纯内存单测，无需起容器。
    yield


class FakeMessageHistory:
    def __init__(self, *, has_checkpoint_fn: bool, checkpoint_failed: bool = False) -> None:
        self.has_checkpoint_fn = has_checkpoint_fn
        self.checkpoint_failed = checkpoint_failed


class FakeLoop:
    """只暴露 _sync_messages 需要的 message_history / messages 接口。"""

    def __init__(self, history: FakeMessageHistory, messages: list[Message]) -> None:
        self._history = history
        self._messages = messages

    @property
    def message_history(self) -> FakeMessageHistory:
        return self._history

    @property
    def messages(self) -> list[Message]:
        return self._messages


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Message]]] = []

    async def save_messages(self, session_id: str, messages: list[Message]) -> None:
        self.calls.append((session_id, messages))


def _compressed_messages() -> list[Message]:
    # 模拟已压缩历史：只剩系统提示 + 一条摘要，若整表覆盖会丢失完整历史。
    return [
        Message(role="system", content="system"),
        Message(role="assistant", content="[已压缩的历史摘要]"),
    ]


async def test_sync_messages_skips_save_when_checkpoint_active() -> None:
    manager = ConnectionManager()
    store = FakeStore()
    loop = FakeLoop(
        FakeMessageHistory(has_checkpoint_fn=True, checkpoint_failed=False),
        _compressed_messages(),
    )

    await manager._sync_messages("s1", loop, store)  # type: ignore[arg-type]  # noqa: SLF001

    assert store.calls == []


async def test_sync_messages_saves_when_no_checkpoint() -> None:
    manager = ConnectionManager()
    store = FakeStore()
    messages = _compressed_messages()
    loop = FakeLoop(FakeMessageHistory(has_checkpoint_fn=False), messages)

    await manager._sync_messages("s1", loop, store)  # type: ignore[arg-type]  # noqa: SLF001

    assert store.calls == [("s1", messages)]


async def test_sync_messages_saves_when_checkpoint_failed() -> None:
    manager = ConnectionManager()
    store = FakeStore()
    messages = _compressed_messages()
    loop = FakeLoop(
        FakeMessageHistory(has_checkpoint_fn=True, checkpoint_failed=True),
        messages,
    )

    await manager._sync_messages("s1", loop, store)  # type: ignore[arg-type]  # noqa: SLF001

    assert store.calls == [("s1", messages)]


async def test_sync_messages_noop_when_store_none() -> None:
    manager = ConnectionManager()
    loop = FakeLoop(
        FakeMessageHistory(has_checkpoint_fn=True, checkpoint_failed=False),
        _compressed_messages(),
    )

    # store 为 None 时应安全返回，不抛异常。
    await manager._sync_messages("s1", loop, None)  # type: ignore[arg-type]  # noqa: SLF001
