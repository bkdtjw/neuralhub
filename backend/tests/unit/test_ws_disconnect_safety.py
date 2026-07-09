from __future__ import annotations

import asyncio

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
    """只暴露 _sync_messages / 回收所需的 message_history / messages / abort 接口。"""

    def __init__(self, history: FakeMessageHistory, messages: list[Message]) -> None:
        self._history = history
        self._messages = messages
        self.aborted = False

    @property
    def message_history(self) -> FakeMessageHistory:
        return self._history

    @property
    def messages(self) -> list[Message]:
        return self._messages

    def abort(self) -> None:
        self.aborted = True


class ExplodingStore:
    """save_messages 记录调用后抛错，模拟断开时落盘失败。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def save_messages(self, session_id: str, messages: list[Message]) -> None:
        self.calls.append(session_id)
        raise RuntimeError("save boom")


async def _never_ending() -> None:
    await asyncio.Event().wait()


async def test_disconnect_cleans_up_even_when_sync_messages_raises() -> None:
    manager = ConnectionManager()
    session_id = "s1"
    websocket = object()
    store = ExplodingStore()
    loop = FakeLoop(FakeMessageHistory(has_checkpoint_fn=False), [])
    manager._loops[session_id] = loop  # type: ignore[assignment]  # noqa: SLF001
    # 多客户端模型（feat/event-hooks）：_connections 存 set[WebSocket]、_subscriber_tasks 存 dict[WebSocket, Task]。
    manager._connections[session_id] = {websocket}  # type: ignore[arg-type]  # noqa: SLF001
    subscriber_task = asyncio.create_task(_never_ending())
    manager._subscriber_tasks[session_id] = {websocket: subscriber_task}  # type: ignore[dict-item]  # noqa: SLF001
    await asyncio.sleep(0)  # 让订阅任务真正进入监听状态

    # 落盘失败（save_messages 抛错）不应向外抛异常，也不应阻断清理。
    await manager.disconnect(
        session_id,
        websocket=websocket,  # type: ignore[arg-type]
        subscriber_task=subscriber_task,
        store=store,  # type: ignore[arg-type]
    )

    assert store.calls == [session_id]  # 确实走到了会抛错的落盘分支
    # B4：无在跑任务的会话，断连后应回收 loop（abort + 从 _loops 移除），即便落盘抛错。
    assert loop.aborted is True
    assert session_id not in manager._loops  # noqa: SLF001
    # cancel 在 disconnect 内同步请求，此处应已登记（不依赖任务已被 await）。
    assert subscriber_task.cancelling() > 0
    assert session_id not in manager._subscriber_tasks  # noqa: SLF001
    assert session_id not in manager._connections  # noqa: SLF001

    # 收尾：让取消真正落地，避免 "task was destroyed but it is pending" 告警。
    with pytest.raises(asyncio.CancelledError):
        await subscriber_task
    assert subscriber_task.cancelled()


async def test_disconnect_cleans_up_without_loop() -> None:
    manager = ConnectionManager()
    session_id = "s2"
    websocket = object()
    store = ExplodingStore()
    # 多客户端模型：set[WebSocket] / dict[WebSocket, Task]。
    manager._connections[session_id] = {websocket}  # type: ignore[arg-type]  # noqa: SLF001
    subscriber_task = asyncio.create_task(_never_ending())
    manager._subscriber_tasks[session_id] = {websocket: subscriber_task}  # type: ignore[dict-item]  # noqa: SLF001
    await asyncio.sleep(0)

    # 无 loop 时仍应完成订阅/连接清理，且根本不触碰 store。
    await manager.disconnect(
        session_id,
        websocket=websocket,  # type: ignore[arg-type]
        subscriber_task=subscriber_task,
        store=store,  # type: ignore[arg-type]
    )

    assert store.calls == []
    assert subscriber_task.cancelling() > 0
    assert session_id not in manager._subscriber_tasks  # noqa: SLF001
    assert session_id not in manager._connections  # noqa: SLF001

    with pytest.raises(asyncio.CancelledError):
        await subscriber_task
    assert subscriber_task.cancelled()
