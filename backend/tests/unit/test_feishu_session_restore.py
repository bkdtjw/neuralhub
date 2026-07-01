from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.common.types import AgentConfig, Message, ProviderConfig, ProviderType, Session, SessionConfig, ToolCall, ToolResult
from backend.core.s01_agent_loop import MessageHistory

from .redis_test_support import use_fake_redis


def _make_event(text: str, event_id: str = "evt_001", chat_id: str = "oc_abc") -> dict[str, Any]:
    return {
        "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"user_id": "u1"}, "sender_type": "user"},
            "message": {
                "message_id": "om_abc",
                "chat_id": chat_id,
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }


def _provider() -> ProviderConfig:
    return ProviderConfig(
        id="provider-1",
        name="anthropic-default",
        provider_type=ProviderType.ANTHROPIC,
        base_url="https://example.com",
        api_key="",
        default_model="provider-model",
        available_models=["provider-model"],
        is_default=True,
    )


def _stored_session(provider_id: str) -> Session:
    return Session(
        id="oc_abc",
        config=SessionConfig(model="stored-model", provider=provider_id, system_prompt="stored prompt"),
        messages=[
            Message(role="system", content="old prompt"),
            Message(role="user", content="first turn"),
            Message(
                role="assistant",
                content="first answer",
                provider_metadata={"thinking_blocks": [{"type": "thinking", "thinking": "kept"}]},
            ),
        ],
        created_at=datetime.utcnow(),
    )


class FakeLoop:
    def __init__(self) -> None:
        self._config = AgentConfig(model="loop-model", provider="loop-provider", system_prompt="fresh prompt", session_id="oc_abc")
        self.message_history = MessageHistory()
        self.messages_before_run: list[Message] = []

    @property
    def messages(self) -> list[Message]:
        return self.message_history.messages

    async def run(self, text: str) -> Message:
        messages = self.message_history.raw_messages
        self.messages_before_run = [message.model_copy(deep=True) for message in messages]
        if not messages and self._config.system_prompt:
            messages.append(Message(role="system", content=self._config.system_prompt))
        messages.append(Message(role="user", content=text))
        tool_call = ToolCall(id="call_echo", name="echo", arguments={"text": text})
        messages.append(
            Message(
                role="assistant",
                content="",
                tool_calls=[tool_call],
                provider_metadata={"thinking_blocks": [{"type": "thinking", "thinking": "step"}]},
            )
        )
        messages.append(Message(role="tool", content="", tool_results=[ToolResult(tool_call_id="call_echo", output="ok")]))
        final = Message(role="assistant", content=f"final:{text}")
        messages.append(final)
        return final


@pytest.fixture(autouse=True)
async def _init_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    await use_fake_redis(monkeypatch)


@pytest.mark.asyncio
async def test_handle_message_restores_session_and_persists_full_turn() -> None:
    client = AsyncMock()
    provider = _provider()
    pm = AsyncMock()
    pm.list_all = AsyncMock(return_value=[provider])
    pm.get_adapter = AsyncMock(return_value=object())
    handler = FeishuMessageHandler(client, pm)
    handler._store = AsyncMock()
    handler._store.get = AsyncMock(return_value=_stored_session(provider.id))
    handler._store.ensure_session = AsyncMock()
    handler._store.save_messages = AsyncMock()
    handler._store.add_messages = AsyncMock()
    loop = FakeLoop()

    with patch("backend.api.routes.feishu_handler.build_agent_loop", new=AsyncMock(return_value=loop)):
        await handler.handle_message(_make_event("follow up"))

    assert [item.role for item in loop.messages_before_run] == ["system", "user", "assistant"]
    assert loop.messages_before_run[0].content == "stored prompt"
    assert loop.messages_before_run[2].provider_metadata["thinking_blocks"][0]["thinking"] == "kept"
    assert loop._config.model == "stored-model"
    persisted = handler._store.save_messages.await_args.args[1]
    assert [item.role for item in persisted] == ["user", "assistant", "user", "assistant", "tool", "assistant"]
    assert persisted[3].tool_calls is not None
    assert persisted[3].tool_calls[0].name == "echo"
    assert persisted[4].tool_results is not None
    assert persisted[4].tool_results[0].output == "ok"
    handler._store.add_messages.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_refreshes_stale_cached_loop_from_store() -> None:
    client = AsyncMock()
    provider = _provider()
    pm = AsyncMock()
    pm.list_all = AsyncMock(return_value=[provider])
    pm.get_adapter = AsyncMock(return_value=object())
    handler = FeishuMessageHandler(client, pm)
    handler._store = AsyncMock()
    handler._store.get = AsyncMock(return_value=_stored_session(provider.id))
    handler._store.ensure_session = AsyncMock()
    handler._store.save_messages = AsyncMock()
    handler._store.add_messages = AsyncMock()
    stale_loop = FakeLoop()
    stale_loop._config.provider = provider.id
    stale_loop.message_history.restore(
        [Message(role="system", content="stale prompt"), Message(role="user", content="stale turn")]
    )
    handler._sessions["oc_abc"] = stale_loop

    with patch("backend.api.routes.feishu_handler.build_agent_loop", new=AsyncMock()) as mock_build:
        await handler.handle_message(_make_event("follow up", event_id="evt_002"))

    mock_build.assert_not_awaited()
    assert stale_loop.messages_before_run[0].content == "stored prompt"
    assert stale_loop.messages_before_run[1].content == "first turn"


def test_restore_messages_patches_orphan_tool_calls() -> None:
    from backend.api.routes.websocket_support import restore_messages

    restored = restore_messages(
        [
            Message(role="user", content="run"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call-1", name="run_task_now", arguments={"task_id": "task-1"})],
            ),
            Message(role="assistant", content="done"),
            Message(
                role="tool",
                content="",
                tool_results=[ToolResult(tool_call_id="call-1", output="late result")],
            ),
        ],
        "system prompt",
    )

    assert [message.role for message in restored] == ["system", "user", "assistant", "tool", "assistant"]
    assert restored[3].tool_results is not None
    assert restored[3].tool_results[0].tool_call_id == "call-1"
    assert restored[4].content == "done"
