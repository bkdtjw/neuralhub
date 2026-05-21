from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.feishu_plan_support import _plan_result_text
from backend.api.routes.feishu_tool_approval import build_tool_approval_card
from backend.common.types import Message
from backend.core.s01_agent_loop import TodoState, TodoStep
from backend.schemas.feishu import FeishuCardAction, FeishuCardActionPayload, FeishuCardActionValue
from backend.tests.unit.test_feishu_plan import MockFeishuClient, _event, _handler


@pytest.mark.asyncio
async def test_tool_card_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.api.routes import feishu_card_action, feishu_card_approval

    fake_handler = MagicMock()
    fake_handler.resolve_tool_call.return_value = True
    monkeypatch.setattr(feishu_card_approval, "_get_handler", lambda: fake_handler)
    payload = FeishuCardActionPayload(
        open_id="ou_1",
        action=FeishuCardAction(
            value=FeishuCardActionValue(
                action="tool_approve",
                tool_call_id="call_1",
                tool_name="send_email",
                chat_id="oc_1",
                owner_id="ou_1",
            )
        ),
    )
    result = await feishu_card_action.dispatcher.dispatch(payload)
    fake_handler.resolve_tool_call.assert_called_once_with("oc_1", "call_1", True, "ou_1")
    assert result["toast"]["type"] == "info"
    assert "card" not in result


def test_tool_approval_card_includes_review_reason() -> None:
    card = build_tool_approval_card(
        [
            {
                "id": "call_1",
                "name": "send_email",
                "arguments": {"to": "all@example.com"},
                "approval_reason": "收件人范围不一致",
            }
        ],
        chat_id="oc_1",
        owner_id="ou_1",
        session_id="feishu-oc_1",
    )
    assert "收件人范围不一致" in card["elements"][0]["content"]
    assert card["elements"][1]["actions"][0]["value"]["tool_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_plan_message_routing() -> None:
    handler = _handler()
    handler._handle_plan_message = AsyncMock()
    await handler.handle_message(_event("/plan 重构 s07"))
    handler._handle_plan_message.assert_called_once_with("oc_1", "重构 s07", "", "oc_1")


@pytest.mark.asyncio
async def test_plan_during_execution_rejected() -> None:
    client = MockFeishuClient()
    handler = _handler(client)
    handler._plan_runners["oc_1"] = object()
    await handler.handle_message(_event("普通消息"))
    assert "正在执行计划" in json.loads(client.sent_messages[0][1])["text"]


def test_plan_result_text_does_not_hide_failed_steps() -> None:
    class Runner:
        _todo_state = TodoState(
            plan_name="p1",
            session_id="feishu",
            status="completed",
            steps=[
                TodoStep(id=1, title="done", status="done", output_summary="partial"),
                TodoStep(id=2, title="report", status="failed", output_summary="步骤执行超时"),
            ],
        )

        def build_exit_summary(self) -> Message:
            return Message(role="assistant", content="exit summary with failed step")

    assert _plan_result_text(Runner()) == "exit summary with failed step"  # type: ignore[arg-type]
