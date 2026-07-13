from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from backend.common.errors import AgentError
from backend.common.logging import get_logger
from backend.config import get_redis, get_redis_pubsub

logger = get_logger(component="pubsub")


class PubSubError(AgentError):
    pass


def ws_session_channel(session_id: str) -> str:
    return f"ws:session:{session_id}"


def task_event_channel(task_id: str) -> str:
    return f"task:event:{task_id}"


async def publish(channel: str, message: dict[str, Any]) -> None:
    try:
        redis = _require_redis()
        await redis.publish(channel, json.dumps(message, ensure_ascii=False))
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("pubsub_publish_failed", channel=channel)
        raise PubSubError("PUBSUB_PUBLISH_ERROR", str(exc)) from exc


class Subscriber:
    def __init__(self, poll_timeout: float = 1.0) -> None:
        self._poll_timeout = poll_timeout
        self._channels: set[str] = set()
        self._pubsub: Any | None = None

    async def subscribe(self, channel: str) -> None:
        try:
            if self._pubsub is None:
                # 订阅走独立 pubsub 池：连接按 WS 会话生命周期长期占用，不与 publish 抢命令池。
                self._pubsub = _require_pubsub_redis().pubsub()
            await self._pubsub.subscribe(channel)
            self._channels.add(channel)
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PubSubError("PUBSUB_SUBSCRIBE_ERROR", str(exc)) from exc

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        try:
            pubsub = self._require_pubsub()
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=self._poll_timeout,
                )
                if message is None or message.get("type") != "message":
                    continue
                yield json.loads(str(message.get("data", "{}")))
        except AgentError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PubSubError("PUBSUB_LISTEN_ERROR", str(exc)) from exc

    async def unsubscribe(self) -> None:
        try:
            if self._pubsub is None:
                return
            channels = list(self._channels)
            self._channels.clear()
            if channels:
                await self._pubsub.unsubscribe(*channels)
            close = getattr(self._pubsub, "aclose", None)
            if callable(close):
                await close()
            self._pubsub = None
        except Exception as exc:  # noqa: BLE001
            raise PubSubError("PUBSUB_UNSUBSCRIBE_ERROR", str(exc)) from exc

    def _require_pubsub(self) -> Any:
        if self._pubsub is None:
            raise PubSubError("PUBSUB_NOT_SUBSCRIBED", "Subscriber has not subscribed to any channels.")
        return self._pubsub


def _require_redis() -> Any:
    redis = get_redis()
    if redis is None:
        raise PubSubError("PUBSUB_REDIS_UNAVAILABLE", "Redis client is not initialized.")
    return redis


def _require_pubsub_redis() -> Any:
    redis = get_redis_pubsub()
    if redis is None:
        raise PubSubError("PUBSUB_REDIS_UNAVAILABLE", "Redis pubsub client is not initialized.")
    return redis


__all__ = [
    "PubSubError",
    "Subscriber",
    "publish",
    "task_event_channel",
    "ws_session_channel",
]
