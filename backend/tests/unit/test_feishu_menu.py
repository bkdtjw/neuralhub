from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes import feishu
from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.common.types import Message
from backend.core.s01_agent_loop import PlanControlStore
from backend.core.s02_tools.builtin.feishu_client import FeishuClient


class MenuClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.reply_message = AsyncMock()

    async def send_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        receive_id_type: str = "chat_id",
    ) -> dict[str, Any]:
        self.sent.append((chat_id, content, receive_id_type))
        return {"code": 0}


def _handler(client: MenuClient | None = None) -> FeishuMessageHandler:
    pm = AsyncMock()
    handler = FeishuMessageHandler(client or MenuClient(), pm)
    handler._seen = AsyncMock(return_value=False)
    return handler


def _event(text: str, open_id: str = "ou_test") -> dict[str, Any]:
    return {
        "header": {"event_id": "evt_1", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": open_id}},
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_1",
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }


@pytest.mark.asyncio
async def test_bot_menu_event_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = MagicMock()
    handler.handle_menu_event = AsyncMock()
    monkeypatch.setattr(feishu, "_handler", handler)
    app = FastAPI()
    app.include_router(feishu.router)
    payload = {
        "schema": "2.0",
        "header": {"event_type": "application.bot.menu_v6", "event_id": "evt_menu"},
        "event": {"event_key": "plan_mode", "operator": {"operator_id": {"open_id": "ou_test"}}},
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/feishu/event", json=payload)
    assert response.json() == {"code": 0}
    handler.handle_menu_event.assert_awaited_once_with("plan_mode", "ou_test")


@pytest.mark.asyncio
async def test_card_action_event_payload_dispatched() -> None:
    handler = MagicMock()
    handler.approve_plan.return_value = True
    feishu.set_handler(handler)
    app = FastAPI()
    app.include_router(feishu.router)
    payload = {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger", "event_id": "evt_card"},
        "event": {
            "operator": {"open_id": "ou_test"},
            "context": {"open_message_id": "om_1", "open_chat_id": "oc_1"},
            "action": {
                "tag": "button",
                "value": {
                    "action_type": "plan_approve",
                    "plan_name": "p1",
                    "chat_id": "oc_1",
                    "owner_id": "ou_test",
                },
            },
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/feishu/event", json=payload)
    assert response.json()["toast"]["content"] == "计划 p1 已批准，开始执行"
    feishu.set_handler(None)


@pytest.mark.asyncio
async def test_menu_mode_switches_and_confirms() -> None:
    client = MenuClient()
    handler = _handler(client)
    handler._user_chats["ou_test"] = "oc_known"
    await handler.handle_menu_event("plan_mode", "ou_test")
    assert handler._user_modes["ou_test"] == "plan_execute"
    assert client.sent[-1][0] == "oc_known"
    assert client.sent[-1][2] == "chat_id"
    await handler.handle_menu_event("direct_mode", "ou_test")
    assert "ou_test" not in handler._user_modes
    assert "普通模式" in json.loads(client.sent[-1][1])["text"]
    await handler.handle_menu_event("unknown", "ou_test")
    assert "ou_test" not in handler._user_modes


@pytest.mark.asyncio
async def test_direct_mode_stops_active_plan_for_latest_chat(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAN_CONTROL_DIR", str(tmp_path / "controls"))
    client = MenuClient()
    handler = _handler(client)
    runner = MagicMock()
    handler._user_chats["ou_test"] = "oc_known"
    handler._user_modes["ou_test"] = "plan_execute"
    handler._plan_runners["oc_known"] = runner

    await handler.handle_menu_event("direct_mode", "ou_test")

    runner.cancel.assert_called_once_with()
    assert "ou_test" not in handler._user_modes
    assert PlanControlStore().read("feishu-oc_known").action == "stop"
    assert "已停止当前计划" in json.loads(client.sent[-1][1])["text"]


@pytest.mark.asyncio
async def test_menu_confirmation_falls_back_to_open_id() -> None:
    client = MenuClient()
    handler = _handler(client)
    await handler.handle_menu_event("plan_mode", "ou_test")
    assert client.sent[-1][0] == "ou_test"
    assert client.sent[-1][2] == "open_id"


@pytest.mark.asyncio
async def test_plan_mode_routes_plain_message_to_plan_handler() -> None:
    handler = _handler()
    handler._user_modes["ou_test"] = "plan_execute"
    handler._handle_plan_message = AsyncMock()
    await handler.handle_message(_event("重构 s07"))
    handler._handle_plan_message.assert_awaited_once_with("oc_1", "重构 s07", owner_id="ou_test")


@pytest.mark.asyncio
async def test_direct_mode_routes_plain_message_to_normal_loop() -> None:
    handler = _handler()
    loop = AsyncMock()
    loop.run = AsyncMock(return_value=Message(role="assistant", content="normal reply"))
    loop._config = MagicMock(provider="provider-1")
    handler._get_or_create_loop = AsyncMock(return_value=loop)
    handler._persist_turn = AsyncMock()
    handler._try_reply_card = AsyncMock(return_value=False)
    await handler.handle_message(_event("普通消息"))
    handler._get_or_create_loop.assert_awaited_once_with("oc_1", "ou_test")
    loop.run.assert_awaited_once_with("普通消息")


@pytest.mark.asyncio
async def test_slash_plan_works_and_plan_mode_persists() -> None:
    class Runner:
        async def run(self, message: str) -> None:
            self.message = message

        def build_exit_summary(self) -> Message:
            return Message(role="assistant", content="summary")

    handler = _handler()
    handler._handle_plan_message = AsyncMock()
    await handler.handle_message(_event("/plan 重构 s07"))
    handler._handle_plan_message.assert_awaited_once_with("oc_1", "重构 s07", "", "ou_test")
    handler._user_modes["ou_test"] = "plan_execute"
    runner = Runner()
    handler._plan_runners["oc_1"] = runner
    await handler._run_plan("oc_1", runner, "task")
    assert handler._user_modes["ou_test"] == "plan_execute"


@pytest.mark.asyncio
async def test_send_message_receive_id_type() -> None:
    client = FeishuClient("app", "secret")
    client._token = "token"
    client._token_expires = time.time() + 3600
    calls: list[dict[str, Any]] = []
    response = MagicMock()
    response.json.return_value = {"code": 0}

    async def mock_post(*args: Any, **kwargs: Any) -> MagicMock:
        calls.append({"args": args, "kwargs": kwargs})
        return response

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        await client.send_message("ou_test", json.dumps({"text": "hi"}), receive_id_type="open_id")
        await client.send_message("oc_test", json.dumps({"text": "hi"}))
    assert calls[0]["kwargs"]["params"]["receive_id_type"] == "open_id"
    assert calls[0]["kwargs"]["json"]["receive_id"] == "ou_test"
    assert calls[1]["kwargs"]["params"]["receive_id_type"] == "chat_id"
