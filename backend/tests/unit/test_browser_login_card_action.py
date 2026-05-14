from __future__ import annotations

import pytest

from backend.api.routes.browser_login_card_action import _handle_browser_login
from backend.core.s02_tools.builtin.browser_agent.login_session import BrowserLoginSessionManager
from backend.schemas.feishu import FeishuCardActionPayload


@pytest.mark.asyncio
async def test_browser_login_card_action_submits_form_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BrowserLoginSessionManager()
    calls: list[tuple[str, str, dict[str, str]]] = []

    async def submit(action_type: str, session_id: str, values: dict[str, str]) -> bool:
        calls.append((action_type, session_id, values))
        return True

    monkeypatch.setattr(
        "backend.api.routes.browser_login_card_action.browser_login_manager",
        manager,
    )
    monkeypatch.setattr(manager, "submit", submit)

    payload = FeishuCardActionPayload.model_validate(
        {
            "action": {
                "value": {
                    "action_type": "browser_login_sms_request",
                    "session_id": "sid",
                },
                "form_value": {"phone": "13800000000"},
            }
        }
    )

    result = await _handle_browser_login(payload)

    assert result["toast"]["type"] == "info"
    assert calls == [
        (
            "browser_login_sms_request",
            "sid",
            {
                "action_type": "browser_login_sms_request",
                "session_id": "sid",
                "phone": "13800000000",
            },
        )
    ]


@pytest.mark.asyncio
async def test_browser_login_card_action_falls_back_to_message_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BrowserLoginSessionManager()
    calls: list[str] = []

    async def submit(action_type: str, session_id: str, values: dict[str, str]) -> bool:
        calls.append(session_id)
        return True

    monkeypatch.setattr(
        "backend.api.routes.browser_login_card_action.browser_login_manager",
        manager,
    )
    monkeypatch.setattr(manager, "submit", submit)
    monkeypatch.setattr(manager, "session_for_message", lambda message_id: "sid-from-message")

    payload = FeishuCardActionPayload.model_validate(
        {
            "open_message_id": "om_1",
            "action": {
                "value": {"action_type": "browser_login_sms_submit"},
                "form_value": {"code": "123456"},
            },
        }
    )

    result = await _handle_browser_login(payload)

    assert result["toast"]["type"] == "info"
    assert calls == ["sid-from-message"]
