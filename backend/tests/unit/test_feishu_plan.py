from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.api.routes.feishu_plan_renderer import FeishuPlanRenderer
from backend.common.types import ProviderConfig, ProviderType
from backend.core.s01_agent_loop import ExecutionPlan, PlanStep, TodoState
from backend.schemas.feishu import FeishuCardAction, FeishuCardActionPayload, FeishuCardActionValue


class MockFeishuClient:
    def __init__(self, fail_update: bool = False) -> None:
        self.fail_update = fail_update
        self.send_card_count = 0
        self.update_card_count = 0
        self.last_card_content: dict[str, Any] = {}
        self.last_update_message_id = ""
        self.sent_messages: list[tuple[str, str]] = []

    async def send_card(self, chat_id: str, card_content: dict[str, Any]) -> str:
        self.send_card_count += 1
        self.last_card_content = card_content
        return "om_card_1"

    async def update_card(self, message_id: str, card_content: dict[str, Any]) -> bool:
        if self.fail_update:
            raise RuntimeError("patch failed")
        self.update_card_count += 1
        self.last_update_message_id = message_id
        self.last_card_content = card_content
        return True

    async def send_message(self, chat_id: str, content: str, msg_type: str = "text") -> None:
        self.sent_messages.append((chat_id, content))


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        goal="test",
        overall_summary="计划摘要",
        risks=["风险1"],
        steps=[
            PlanStep(step_id=1, title="step1", description="d1"),
            PlanStep(step_id=2, title="step2", description="d2"),
        ],
    )


def _todo(status: str = "completed") -> TodoState:
    return TodoState(plan_name="test-plan", session_id="feishu", status=status)


def _has_action(card: dict[str, Any]) -> bool:
    return any(element.get("tag") == "action" for element in card["elements"])


def _event(text: str) -> dict[str, Any]:
    return {
        "header": {"event_id": "evt_1", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user"},
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_1",
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }


def _handler(client: MockFeishuClient | None = None) -> FeishuMessageHandler:
    provider = ProviderConfig(
        id="provider-1",
        name="Provider",
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="https://example.com",
        api_key="",
        default_model="model",
        available_models=["model"],
        is_default=True,
    )
    pm = AsyncMock()
    pm.list_all = AsyncMock(return_value=[provider])
    handler = FeishuMessageHandler(client or MockFeishuClient(), pm)
    handler._seen = AsyncMock(return_value=False)
    return handler


@pytest.mark.asyncio
async def test_feishu_renderer_sends_initial_card_with_buttons() -> None:
    client = MockFeishuClient()
    renderer = FeishuPlanRenderer(client, "chat_123")
    await renderer.on_plan_created(_plan(), "test-plan")
    action = next(
        element for element in client.last_card_content["elements"] if element["tag"] == "action"
    )
    assert renderer.message_id == "om_card_1"
    assert client.send_card_count == 1
    assert action["actions"][0]["value"]["plan_name"] == "test-plan"
    assert action["actions"][0]["value"]["session_id"] == "feishu-chat_123"
    assert action["actions"][0]["text"]["content"] == "开始执行"
    assert action["actions"][1]["url"].endswith("/reports/plans/feishu-chat_123-test-plan.md")
    assert action["actions"][2]["value"]["action"] == "plan_adjust"
    assert action["actions"][3]["value"]["action"] == "plan_cancel"


@pytest.mark.asyncio
async def test_feishu_renderer_updates_same_card() -> None:
    client = MockFeishuClient()
    renderer = FeishuPlanRenderer(client, "chat_123")
    await renderer.on_plan_created(_plan(), "test-plan")
    await renderer.on_step_start(1, "step1", 2)
    await renderer.on_step_done(1, "step1", 3.2, "ok")
    assert client.update_card_count == 2
    assert client.last_update_message_id == "om_card_1"
    assert "✅ **step1** (3.2s)" in client.last_card_content["elements"][0]["content"]


@pytest.mark.asyncio
async def test_feishu_renderer_final_cards_and_failure_silent() -> None:
    client = MockFeishuClient()
    renderer = FeishuPlanRenderer(client, "chat_123")
    await renderer.on_plan_created(_plan(), "test-plan")
    await renderer.on_plan_completed("test-plan", _todo())
    assert client.last_card_content["header"]["template"] == "green"
    assert not _has_action(client.last_card_content)
    cancelled = FeishuPlanRenderer(client, "chat_123")
    await cancelled.on_plan_created(_plan(), "test-plan")
    await cancelled.on_plan_cancelled("test-plan", _todo("cancelled"))
    assert client.last_card_content["header"]["template"] == "red"
    assert "已跳过" in client.last_card_content["elements"][0]["content"]
    partial = FeishuPlanRenderer(client, "chat_123")
    await partial.on_plan_created(_plan(), "test-plan")
    await partial.on_plan_partial_failed("test-plan", _todo("partial_failed"), 1, 1)
    assert client.last_card_content["header"]["template"] == "orange"
    failing = FeishuPlanRenderer(MockFeishuClient(fail_update=True), "chat_123")
    await failing.on_plan_created(_plan(), "test-plan")
    await failing.on_step_done(1, "step1", 1.0, "ok")


@pytest.mark.asyncio
async def test_plan_card_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.api.routes import feishu_card_action, feishu_card_approval

    fake_handler = MagicMock()
    fake_handler.approve_plan.return_value = True
    fake_handler.reject_plan.return_value = True
    fake_handler.cancel_plan.return_value = True
    fake_handler._send_chat_text = AsyncMock()
    monkeypatch.setattr(feishu_card_approval, "_get_handler", lambda: fake_handler)
    payload = FeishuCardActionPayload(
        open_id="ou_1",
        action=FeishuCardAction(
            value=FeishuCardActionValue(
                action="plan_approve",
                plan_name="p1",
                chat_id="oc_1",
                owner_id="ou_1",
            )
        ),
    )
    assert (await feishu_card_action.dispatcher.dispatch(payload))["toast"]["type"] == "info"
    fake_handler.approve_plan.assert_called_once_with("oc_1", "p1", "ou_1")
    cancel_payload = FeishuCardActionPayload(
        open_id="ou_1",
        action=FeishuCardAction(
            value=FeishuCardActionValue(
                action="plan_cancel",
                plan_name="p1",
                chat_id="oc_1",
                owner_id="ou_1",
            ),
        ),
    )
    result = await feishu_card_action.dispatcher.dispatch(cancel_payload)
    fake_handler.reject_plan.assert_called_once_with("oc_1", "p1", "ou_1")
    assert result["toast"]["type"] == "warning"
    adjust_payload = FeishuCardActionPayload(
        open_id="ou_1",
        action=FeishuCardAction(
            value=FeishuCardActionValue(
                action="plan_adjust",
                plan_name="p1",
                chat_id="oc_1",
                owner_id="ou_1",
            ),
        ),
    )
    result = await feishu_card_action.dispatcher.dispatch(adjust_payload)
    assert result["toast"]["type"] == "info"
    fake_handler._send_chat_text.assert_called_once()
