"""G1: Redis 不可用时飞书去重降级 —— 不静默丢弃消息。"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.api.routes import feishu as feishu_route
from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.common.errors import AgentError
from backend.core.s01_agent_loop import MessageHistory

from .redis_test_support import use_fake_redis


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存（fakeredis + mock store），跳过 PostgresContainer。
    yield


@pytest_asyncio.fixture(autouse=True)
async def _init_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)


def _make_event(text: str = "hello", event_id: str = "evt_001") -> dict[str, Any]:
    return {
        "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"user_id": "u1"}, "sender_type": "user"},
            "message": {
                "message_id": "om_abc",
                "chat_id": "oc_abc",
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }


def _mock_handler() -> tuple[FeishuMessageHandler, AsyncMock]:
    client = AsyncMock()
    pm = AsyncMock()
    provider = MagicMock(id="provider-1", is_default=True, default_model="model-1")
    provider.provider_type.value = "provider-1"
    pm.list_all.return_value = [provider]
    handler = FeishuMessageHandler(client, pm)
    handler._store = AsyncMock()
    handler._store.get = AsyncMock(return_value=None)
    loop = AsyncMock()
    loop._config = MagicMock(provider="provider-1")
    loop.message_history = MessageHistory()
    loop.run = AsyncMock(return_value=MagicMock(content="Agent reply"))
    handler._sessions["oc_abc"] = loop
    return handler, client


class TestDedupDegraded:
    @pytest.mark.asyncio
    async def test_dedup_failure_does_not_drop_message(self) -> None:
        handler, client = _mock_handler()
        handler._seen = AsyncMock(side_effect=AgentError("FEISHU_REDIS_UNAVAILABLE", "down"))

        # 不得抛出，且消息仍被处理（去重失败 -> 放行），而非静默丢弃。
        await handler.handle_message(_make_event())

        handler._sessions["oc_abc"].run.assert_called_once_with("hello")
        client.reply_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedup_failure_increments_alarm_metric(self) -> None:
        handler, _ = _mock_handler()
        handler._seen = AsyncMock(side_effect=AgentError("FEISHU_DEDUP_ERROR", "boom"))

        with patch(
            "backend.api.routes.feishu_handler.incr", new=AsyncMock()
        ) as incr_mock:
            await handler.handle_message(_make_event())

        incr_mock.assert_any_await("feishu_dedup_failures")

    @pytest.mark.asyncio
    async def test_dedup_true_skips_processing(self) -> None:
        handler, client = _mock_handler()
        handler._seen = AsyncMock(return_value=True)

        await handler.handle_message(_make_event())

        handler._sessions["oc_abc"].run.assert_not_called()
        client.reply_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_false_processes_message(self) -> None:
        handler, client = _mock_handler()
        handler._seen = AsyncMock(return_value=False)

        await handler.handle_message(_make_event())

        handler._sessions["oc_abc"].run.assert_called_once_with("hello")
        client.reply_message.assert_called_once()


class TestBackgroundTaskCallback:
    @pytest.mark.asyncio
    async def test_logs_and_discards_on_exception(self) -> None:
        async def _boom() -> None:
            raise RuntimeError("kaboom")

        task = asyncio.ensure_future(_boom())
        with contextlib.suppress(RuntimeError):
            await task
        feishu_route._background_tasks.add(task)

        with patch.object(feishu_route, "logger") as log:
            feishu_route._log_task_exception(task)

        log.warning.assert_called_once()
        assert task not in feishu_route._background_tasks

    @pytest.mark.asyncio
    async def test_cancelled_task_is_safe(self) -> None:
        async def _never() -> None:
            await asyncio.sleep(3600)

        task = asyncio.ensure_future(_never())
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        feishu_route._background_tasks.add(task)

        with patch.object(feishu_route, "logger") as log:
            feishu_route._log_task_exception(task)  # 不得抛 CancelledError

        log.warning.assert_not_called()
        assert task not in feishu_route._background_tasks

    @pytest.mark.asyncio
    async def test_successful_task_does_not_warn(self) -> None:
        async def _ok() -> None:
            return None

        task = asyncio.ensure_future(_ok())
        await task
        feishu_route._background_tasks.add(task)

        with patch.object(feishu_route, "logger") as log:
            feishu_route._log_task_exception(task)

        log.warning.assert_not_called()
        assert task not in feishu_route._background_tasks
