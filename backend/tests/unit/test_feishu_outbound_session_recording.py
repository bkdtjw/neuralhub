from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.common.types import AgentConfig


class FakeLoop:
    def __init__(self, provider: str) -> None:
        self._config = AgentConfig(
            model=f"{provider}-model",
            provider=provider,
            system_prompt=f"{provider} prompt",
            session_id=f"oc_{provider}",
        )


@pytest.mark.asyncio
async def test_send_chat_text_records_runtime_context() -> None:
    client = AsyncMock()
    handler = FeishuMessageHandler(client, AsyncMock())
    handler._store = AsyncMock()
    handler._store.ensure_session = AsyncMock()
    handler._store.add_messages = AsyncMock()
    handler._sessions["oc_abc"] = FakeLoop("right")
    handler._sessions["oc_other"] = FakeLoop("wrong")

    await handler._send_chat_text("oc_abc", "已发送字幕附件")

    client.send_message.assert_awaited_once()
    handler._store.ensure_session.assert_awaited_once()
    assert handler._store.ensure_session.await_args.kwargs["provider"] == "right"
    handler._store.add_messages.assert_awaited_once()
    message = handler._store.add_messages.await_args.args[1][0]
    assert message.role == "user"
    assert message.kind == "runtime_context"
    assert "已发送字幕附件" in message.content
    assert message.provider_metadata["feishu"]["body_status"] == "inline"
