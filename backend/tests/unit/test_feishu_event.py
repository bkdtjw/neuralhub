"""Tests for Feishu bidirectional communication."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import backend.config.redis_client as redis_client

from backend.common.types import Message, ProviderConfig, ProviderType, Session, SessionConfig
from backend.common.errors import AgentError
from backend.config.settings import settings
from backend.core.s01_agent_loop import MessageHistory
from backend.core.s05_skills import AgentCategory, AgentSpec, SpecRegistry
from .redis_test_support import use_fake_redis
from backend.api.routes.feishu_handler import FeishuMessageHandler, _extract_text


def _make_event(
    text: str = "hello",
    event_id: str = "evt_001",
    chat_id: str = "oc_abc",
    message_id: str = "om_abc",
    sender_type: str = "user",
    msg_type: str = "text",
) -> dict[str, Any]:
    return {
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_id": {"user_id": "u1"}, "sender_type": sender_type},
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "message_type": msg_type,
                "content": json.dumps({"text": text}),
            },
        },
    }


def _mock_handler() -> tuple[FeishuMessageHandler, AsyncMock, AsyncMock]:
    client = AsyncMock()
    pm = AsyncMock()
    provider = MagicMock(id="provider-1", is_default=True, default_model="model-1")
    provider.provider_type.value = "provider-1"
    pm.list_all.return_value = [provider]
    handler = FeishuMessageHandler(client, pm)
    handler._store = AsyncMock()
    handler._store.get = AsyncMock(return_value=None)
    return handler, client, pm


def _mock_loop(**config: Any) -> AsyncMock:
    loop = AsyncMock()
    loop._config = MagicMock(**({"provider": "provider-1"} | config))
    loop.message_history = MessageHistory()
    return loop


@pytest.fixture(autouse=True)
async def _init_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)


class TestUrlVerification:
    @pytest.mark.asyncio
    async def test_challenge_response(self) -> None:
        from backend.api.routes.feishu import router

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/feishu/event",
                json={"type": "url_verification", "challenge": "test123"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "test123"}


class TestMessageHandling:
    @pytest.mark.asyncio
    async def test_normal_message_replies(self) -> None:
        handler, client, pm = _mock_handler()
        mock_loop = _mock_loop()
        mock_result = MagicMock()
        mock_result.content = "Agent reply"
        mock_loop.run = AsyncMock(return_value=mock_result)
        handler._sessions["oc_abc"] = mock_loop

        event = _make_event(text="hello")
        await handler.handle_message(event)

        mock_loop.run.assert_called_once_with("hello")
        client.reply_message.assert_called_once()
        call_args = client.reply_message.call_args
        assert call_args[0][0] == "om_abc"
        assert "Agent reply" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_event_dedup(self) -> None:
        handler, client, pm = _mock_handler()
        mock_loop = _mock_loop()
        mock_result = MagicMock()
        mock_result.content = "reply"
        mock_loop.run = AsyncMock(return_value=mock_result)
        handler._sessions["oc_abc"] = mock_loop

        event = _make_event(event_id="evt_dup")
        await handler.handle_message(event)
        await handler.handle_message(event)

        assert mock_loop.run.call_count == 1

    @pytest.mark.asyncio
    async def test_seen_with_redis_returns_false_first_time(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler, _, _ = _mock_handler()
        await use_fake_redis(monkeypatch)
        assert await handler._seen("evt_redis_first") is False

    @pytest.mark.asyncio
    async def test_seen_with_redis_returns_true_second_time(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler, _, _ = _mock_handler()
        await use_fake_redis(monkeypatch)
        assert await handler._seen("evt_redis_twice") is False
        assert await handler._seen("evt_redis_twice") is True

    @pytest.mark.asyncio
    async def test_seen_raises_when_no_redis(self) -> None:
        handler, _, _ = _mock_handler()
        settings.redis_url = ""
        await redis_client.close_redis()
        with pytest.raises(AgentError, match="FEISHU_REDIS_UNAVAILABLE"):
            await handler._seen("evt_memory")

    @pytest.mark.asyncio
    async def test_seen_raises_when_redis_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler, _, _ = _mock_handler()
        fake = await use_fake_redis(monkeypatch)
        fake.client.fail_operations.add("set")
        with pytest.raises(AgentError, match="FEISHU_DEDUP_ERROR"):
            await handler._seen("evt_redis_error")

    @pytest.mark.asyncio
    async def test_redis_key_has_correct_prefix_and_ttl(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler, _, _ = _mock_handler()
        fake = await use_fake_redis(monkeypatch)
        assert await handler._seen("evt_ttl") is False
        assert "feishu:event:evt_ttl" in fake.client.values
        assert await fake.client.ttl("feishu:event:evt_ttl") == 86400

    @pytest.mark.asyncio
    async def test_bot_message_ignored(self) -> None:
        handler, client, pm = _mock_handler()
        mock_loop = _mock_loop()
        handler._sessions["oc_abc"] = mock_loop

        event = _make_event(sender_type="bot")
        await handler.handle_message(event)

        mock_loop.run.assert_not_called()
        client.reply_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_text_message_replies_unsupported(self) -> None:
        handler, client, pm = _mock_handler()

        event = _make_event(msg_type="image")
        await handler.handle_message(event)

        client.reply_message.assert_called_once()
        reply_json = client.reply_message.call_args[0][1]
        reply_text = json.loads(reply_json)["text"]
        assert "暂不支持" in reply_text

    @pytest.mark.asyncio
    async def test_session_isolation_per_chat(self) -> None:
        handler, client, pm = _mock_handler()
        loop_a = _mock_loop()
        loop_a.run = AsyncMock(return_value=MagicMock(content="reply A"))
        loop_b = _mock_loop()
        loop_b.run = AsyncMock(return_value=MagicMock(content="reply B"))
        handler._sessions["oc_a"] = loop_a
        handler._sessions["oc_b"] = loop_b

        await handler.handle_message(
            _make_event(event_id="evt_a", chat_id="oc_a", text="msg1"),
        )
        await handler.handle_message(
            _make_event(event_id="evt_b", chat_id="oc_b", text="msg2"),
        )

        loop_a.run.assert_called_once_with("msg1")
        loop_b.run.assert_called_once_with("msg2")

    @pytest.mark.asyncio
    async def test_error_sends_error_reply(self) -> None:
        handler, client, pm = _mock_handler()
        mock_loop = _mock_loop()
        mock_loop.run = AsyncMock(side_effect=RuntimeError("boom"))
        handler._sessions["oc_abc"] = mock_loop

        event = _make_event()
        await handler.handle_message(event)

        client.reply_message.assert_called_once()
        reply_json = client.reply_message.call_args[0][1]
        reply_text = json.loads(reply_json)["text"]
        assert "出错" in reply_text

    @pytest.mark.asyncio
    async def test_empty_message_uses_fallback_text(self) -> None:
        handler, client, _ = _mock_handler()
        mock_loop = _mock_loop()
        mock_loop.run = AsyncMock(return_value=Message(role="assistant", content=""))
        handler._sessions["oc_abc"] = mock_loop

        await handler.handle_message(_make_event())

        reply_json = client.reply_message.call_args[0][1]
        reply_text = json.loads(reply_json)["text"]
        assert reply_text == "模型返回了空响应，请重试。"

    @pytest.mark.asyncio
    async def test_get_or_create_loop_uses_provider_default_for_stale_session_model(self) -> None:
        handler, _, pm = _mock_handler()
        provider = ProviderConfig(
            id="provider-1",
            name="Zhipu",
            provider_type=ProviderType.ANTHROPIC,
            base_url="https://open.bigmodel.cn/api/anthropic",
            default_model="glm-5.1",
            available_models=["glm-5.1"],
            is_default=True,
        )
        pm.list_all.return_value = [provider]
        handler._store.get = AsyncMock(
            return_value=Session(
                id="oc_abc",
                config=SessionConfig(model="K2.6-code-preview", provider="anthropic"),
                created_at=datetime.utcnow(),
            )
        )
        loop = _mock_loop(model="glm-5.1", system_prompt="")
        with patch("backend.api.routes.feishu_handler.build_agent_loop", AsyncMock(return_value=loop)) as build_loop:
            await handler._get_or_create_loop("oc_abc")
        assert build_loop.await_args.kwargs["model"] == "glm-5.1"


class TestExtractText:
    def test_text_message(self) -> None:
        msg = {"content": json.dumps({"text": "hello world"})}
        assert _extract_text(msg, "text") == "hello world"

    def test_image_message_returns_none(self) -> None:
        assert _extract_text({}, "image") is None

    def test_empty_text_returns_none(self) -> None:
        msg = {"content": json.dumps({"text": "  "})}
        assert _extract_text(msg, "text") is None

    def test_invalid_json_returns_none(self) -> None:
        assert _extract_text({"content": "not json"}, "text") is None


class TestSlashCommand:
    @pytest.mark.asyncio
    async def test_slash_command_runs_spec_once(self) -> None:
        handler, client, _ = _mock_handler()
        registry = SpecRegistry()
        registry.register(
            AgentSpec(
                id="daily-ai-news",
                title="AI 圈早报",
                category=AgentCategory.AGGREGATION,
                system_prompt="prompt",
            )
        )
        result = MagicMock(content="spec reply")
        loop = AsyncMock()
        loop.run = AsyncMock(return_value=result)
        runtime = AsyncMock()
        runtime.create_loop_from_id = AsyncMock(return_value=loop)
        handler.configure_runtime(runtime, registry, None)
        handler._try_reply_card = AsyncMock(return_value=False)

        await handler.handle_message(_make_event(text="/daily-ai-news"))

        runtime.create_loop_from_id.assert_called_once()
        loop.run.assert_called_once_with("")
        reply_text = json.loads(client.reply_message.call_args[0][1])["text"]
        assert reply_text == "spec reply"

    @pytest.mark.asyncio
    async def test_slash_command_missing_spec_lists_available_specs(self) -> None:
        handler, client, _ = _mock_handler()
        registry = SpecRegistry()
        registry.register(
            AgentSpec(
                id="code-reviewer",
                title="代码审查",
                category=AgentCategory.CODING,
                system_prompt="prompt",
            )
        )
        handler.configure_runtime(AsyncMock(), registry, None)

        await handler.handle_message(_make_event(text="/missing"))

        reply_text = json.loads(client.reply_message.call_args[0][1])["text"]
        assert "未找到场景：missing" in reply_text
        assert "code-reviewer" in reply_text


class TestFeishuClient:
    @pytest.mark.asyncio
    async def test_token_cached(self) -> None:
        from backend.core.s02_tools.builtin.feishu_client import FeishuClient

        client = FeishuClient("app_id", "app_secret")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "tk_123",
            "expire": 7200,
        }

        call_count = 0

        async def mock_post(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            await client._ensure_token()
            await client._ensure_token()

        assert call_count == 1
        assert client._token == "tk_123"


class TestTruncateContent:
    def test_short_content_unchanged(self) -> None:
        from backend.core.s02_tools.builtin.feishu_notify import _truncate_content

        assert _truncate_content("hello") == "hello"

    def test_long_content_truncated(self) -> None:
        from backend.core.s02_tools.builtin.feishu_notify import (
            MAX_FEISHU_CONTENT_LENGTH,
            _truncate_content,
        )

        long_content = "中" * (MAX_FEISHU_CONTENT_LENGTH // 3 * 2)
        result = _truncate_content(long_content)
        assert "已截断" in result
        assert len(result.encode("utf-8")) <= MAX_FEISHU_CONTENT_LENGTH + 200
