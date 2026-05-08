from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.core.s01_agent_loop import PlanControlStore


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


def _handler(client: MenuClient) -> FeishuMessageHandler:
    handler = FeishuMessageHandler(client, AsyncMock())
    handler._seen = AsyncMock(return_value=False)
    return handler


def _event(text: str) -> dict[str, Any]:
    return {
        "header": {"event_id": "evt_1", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_test"}},
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_1",
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }


@pytest.mark.asyncio
async def test_plan_pause_and_stop_menu_controls_current_runner() -> None:
    client = MenuClient()
    handler = _handler(client)
    runner = MagicMock()
    runner.is_paused.return_value = False
    handler._user_chats["ou_test"] = "oc_1"
    handler._plan_runners["oc_1"] = runner
    await handler.handle_menu_event("plan_pause", "ou_test")
    runner.pause.assert_called_once_with()
    assert "已暂停后续步骤" in json.loads(client.sent[-1][1])["text"]
    await handler.handle_menu_event("plan_stop", "ou_test")
    runner.cancel.assert_called_once_with()
    assert "已停止当前计划" in json.loads(client.sent[-1][1])["text"]


@pytest.mark.asyncio
async def test_plan_stop_menu_accepts_leading_equals() -> None:
    client = MenuClient()
    handler = _handler(client)
    runner = MagicMock()
    handler._user_chats["ou_test"] = "oc_1"
    handler._plan_runners["oc_1"] = runner
    await handler.handle_menu_event("=plan_stop", "ou_test")
    runner.cancel.assert_called_once_with()
    assert "已停止当前计划" in json.loads(client.sent[-1][1])["text"]


@pytest.mark.asyncio
async def test_paused_plan_message_resumes_with_instruction() -> None:
    client = MenuClient()
    handler = _handler(client)
    runner = MagicMock()
    runner.is_paused.return_value = True
    handler._plan_runners["oc_1"] = runner
    await handler.handle_message(_event("后续步骤增加验证"))
    runner.resume.assert_called_once_with("后续步骤增加验证")
    assert "已收到补充要求" in json.loads(client.sent[-1][1])["text"]
    runner.resume.reset_mock()
    await handler.handle_message(_event("继续"))
    runner.resume.assert_called_once_with()
    await handler.handle_message(_event("停止"))
    runner.cancel.assert_called_once_with()


@pytest.mark.asyncio
async def test_remote_plan_pause_uses_shared_control(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAN_CONTROL_DIR", str(tmp_path / "controls"))
    monkeypatch.setattr(
        "backend.api.routes.feishu_plan_control.TodoStore",
        lambda: SimpleNamespace(
            list_active=lambda: [SimpleNamespace(session_id="feishu-oc_1", status="executing")]
        ),
    )
    client = MenuClient()
    handler = _handler(client)
    handler._user_chats["ou_test"] = "oc_1"
    await handler.handle_menu_event("plan_pause", "ou_test")
    assert "已暂停后续步骤" in json.loads(client.sent[-1][1])["text"]
    assert PlanControlStore().read("feishu-oc_1").action == "pause"


@pytest.mark.asyncio
async def test_remote_paused_plan_message_resumes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAN_CONTROL_DIR", str(tmp_path / "controls"))
    monkeypatch.setattr(
        "backend.api.routes.feishu_plan_control.TodoStore",
        lambda: SimpleNamespace(
            list_active=lambda: [SimpleNamespace(session_id="feishu-oc_1", status="paused")]
        ),
    )
    client = MenuClient()
    handler = _handler(client)
    await handler.handle_message(_event("继续"))
    assert "已继续执行" in json.loads(client.sent[-1][1])["text"]
    assert PlanControlStore().read("feishu-oc_1").action == "resume"
