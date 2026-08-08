from __future__ import annotations

import asyncio

import pytest

from backend.common.logging import get_worker_id
import backend.core.pubsub as pubsub_module
from backend.core.pubsub import PubSubError, Subscriber, publish, ws_session_channel
from backend.api.routes.websocket_pubsub import WebSocketEnvelope, forward_session_messages

from .redis_test_support import FakeAsyncRedis, use_fake_redis


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.event = asyncio.Event()

    async def send_json(self, payload: dict[str, object]) -> None:
        self.messages.append(payload)
        self.event.set()


@pytest.mark.asyncio
async def test_publish_and_subscribe_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)
    subscriber = Subscriber(poll_timeout=0.05)
    await subscriber.subscribe(ws_session_channel("session-1"))
    await publish(ws_session_channel("session-1"), {"type": "message", "content": "hello"})
    message = await anext(subscriber.listen())
    await subscriber.unsubscribe()
    assert message == {"type": "message", "content": "hello"}


@pytest.mark.asyncio
async def test_forward_session_messages_ignores_same_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)
    websocket = FakeWebSocket()
    task = asyncio.create_task(forward_session_messages("session-2", websocket))
    await asyncio.sleep(0.01)
    await publish(
        ws_session_channel("session-2"),
        WebSocketEnvelope(
            session_id="session-2",
            worker_id=get_worker_id(),
            payload={"type": "status", "status": "thinking"},
        ).model_dump(mode="json"),
    )
    await publish(
        ws_session_channel("session-2"),
        WebSocketEnvelope(
            session_id="session-2",
            worker_id="worker-other",
            payload={"type": "message", "content": "remote"},
        ).model_dump(mode="json"),
    )
    await asyncio.wait_for(websocket.event.wait(), timeout=1)
    task.cancel()
    await task
    assert websocket.messages == [{"type": "message", "content": "remote"}]


@pytest.mark.asyncio
async def test_subscriber_uses_dedicated_pubsub_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 订阅连接长期占用，必须落在独立 pubsub 客户端上，不允许挤占命令池。
    command_client = FakeAsyncRedis()
    pubsub_client = FakeAsyncRedis()
    monkeypatch.setattr(pubsub_module, "get_redis", lambda: command_client)
    monkeypatch.setattr(pubsub_module, "get_redis_pubsub", lambda: pubsub_client)
    subscriber = Subscriber(poll_timeout=0.05)
    channel = ws_session_channel("session-3")
    await subscriber.subscribe(channel)
    assert channel in pubsub_client.subscribers
    assert channel not in command_client.subscribers
    await subscriber.unsubscribe()


@pytest.mark.asyncio
async def test_publish_raises_pubsub_error_when_pool_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 池耗尽（MaxConnectionsError 一类）在 publish 层的契约是抛 PubSubError，
    # 降级（吞掉并告警）由 broadcast 负责，见 test_websocket_connection_manager。
    fake = await use_fake_redis(monkeypatch)
    fake.client.fail_operations.add("publish")
    with pytest.raises(PubSubError, match="PUBSUB_PUBLISH_ERROR"):
        await publish(ws_session_channel("session-4"), {"type": "message"})
