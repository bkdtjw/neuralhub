from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes import feishu_events as feishu_events_module
from backend.api.routes.feishu_card_handlers import CardHandlerDeps, register_all
from backend.api.routes.feishu_events import FeishuEventDispatcher, router
from backend.storage.login_workflow_store import (
    LoginStatus,
    LoginWorkflowStore,
    SiteLoginState,
)


class FakeFeishuClient:
    def __init__(self) -> None:
        self.cards: list[dict] = []

    async def send_card(self, chat_id: str, card_content: dict) -> str:
        self.cards.append(card_content)
        return "message-id"


@pytest.mark.asyncio
async def test_relogin_start_card_event_creates_workflow(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    monkeypatch.setattr(feishu_events_module, "dispatcher", FeishuEventDispatcher())
    client = FakeFeishuClient()
    register_all(
        CardHandlerDeps(
            feishu_client=client,
            chat_id="chat",
            session_factory=db_session_factory,
        )
    )
    store = LoginWorkflowStore(db_session_factory)
    await store.upsert(SiteLoginState(site_id="site1", user_id="u1", status=LoginStatus.EXPIRED))

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "operator": {"operator_id": {"open_id": "u1"}},
            "action": {"value": {"action_type": "relogin_start"}},
        },
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post("/feishu/events", json=payload)

    assert response.status_code == 200
    assert response.json()["site_count"] == 1
    assert client.cards
    states = await store.list_by_status("u1", [LoginStatus.IN_PROGRESS])
    assert states[0].workflow_id
