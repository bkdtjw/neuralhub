from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.adapters.provider_manager import ProviderManager
from backend.api.routes import feishu_plan_resume
from backend.api.routes.feishu_handler import FeishuMessageHandler
from backend.core.s01_agent_loop import PlanPhase, PlanState


class MockFeishuClient:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, content: str, msg_type: str = "text") -> None:
        self.sent_messages.append((chat_id, content))


class FakeProviderManager(ProviderManager):
    def __init__(self) -> None:
        pass


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


def _event_with_sender(text: str) -> dict[str, Any]:
    event = _event(text)
    event["event"]["sender"] = {
        "sender_type": "user",
        "sender_id": {"open_id": "ou_1"},
    }
    return event


def _handler(client: MockFeishuClient) -> FeishuMessageHandler:
    handler = FeishuMessageHandler(client, FakeProviderManager())
    handler._seen = AsyncMock(return_value=False)
    return handler


@pytest.mark.asyncio
async def test_feishu_prompts_and_resumes_incomplete_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MockFeishuClient()
    handler = _handler(client)
    state = PlanState(
        plan_name="resume-plan",
        session_id="feishu-oc_1",
        owner_id="oc_1",
        phase=PlanPhase.EXECUTING,
        current_step_id=2,
    )
    runner = MagicMock()

    class FakeCheckpointStore:
        def find_incomplete_by_owner(self, owner_id: str) -> list[PlanState]:
            return [state]

    async def fake_create_resume_runner(*_args: object) -> object:
        return runner

    async def fake_resume_plan(*_args: object) -> None:
        return None

    monkeypatch.setattr(feishu_plan_resume, "PlanCheckpointStore", FakeCheckpointStore)
    monkeypatch.setattr(feishu_plan_resume, "create_feishu_resume_runner", fake_create_resume_runner)
    monkeypatch.setattr(feishu_plan_resume, "resume_plan", fake_resume_plan)

    await handler.handle_message(_event("普通消息"))
    await handler.handle_message(_event("继续"))
    await asyncio.sleep(0)

    assert "未完成的计划" in json.loads(client.sent_messages[0][1])["text"]
    assert handler._plan_runners["oc_1"] is runner


@pytest.mark.asyncio
async def test_feishu_discard_without_pending_memory_deletes_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MockFeishuClient()
    handler = _handler(client)
    state = PlanState(
        plan_name="resume-plan",
        session_id="feishu-oc_1",
        owner_id="ou_1",
        phase=PlanPhase.EXECUTING,
    )

    class FakeCheckpointStore:
        deleted: list[tuple[str, str]] = []

        def find_incomplete_by_owner(self, owner_id: str) -> list[PlanState]:
            return [state] if owner_id == "ou_1" else []

        def delete(self, session_id: str, plan_name: str) -> bool:
            self.deleted.append((session_id, plan_name))
            return True

    store = FakeCheckpointStore()
    monkeypatch.setattr(feishu_plan_resume, "PlanCheckpointStore", lambda: store)

    await handler.handle_message(_event_with_sender("放弃"))

    assert store.deleted == [("feishu-oc_1", "resume-plan")]
    assert "已切回普通模式" in json.loads(client.sent_messages[0][1])["text"]


@pytest.mark.asyncio
async def test_feishu_discard_clears_plan_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockFeishuClient()
    handler = _handler(client)
    handler._user_modes["ou_1"] = "plan_execute"
    state = PlanState(
        plan_name="resume-plan",
        session_id="feishu-oc_1",
        owner_id="ou_1",
        phase=PlanPhase.EXECUTING,
    )

    class FakeCheckpointStore:
        def find_incomplete_by_owner(self, owner_id: str) -> list[PlanState]:
            return [state] if owner_id == "ou_1" else []

        def delete(self, session_id: str, plan_name: str) -> bool:
            return True

    monkeypatch.setattr(feishu_plan_resume, "PlanCheckpointStore", FakeCheckpointStore)

    await handler.handle_message(_event_with_sender("放弃"))

    assert "ou_1" not in handler._user_modes
