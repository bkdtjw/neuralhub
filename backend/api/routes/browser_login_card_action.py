from __future__ import annotations

from typing import Any

from backend.api.routes.feishu_card_action import dispatcher
from backend.core.s02_tools.builtin.browser_agent.login_session import browser_login_manager
from backend.schemas.feishu import FeishuCardActionPayload

_ACTIONS = (
    "browser_login_sms_open",
    "browser_login_sms_request",
    "browser_login_sms_submit",
    "browser_login_password_open",
    "browser_login_password_submit",
    "browser_login_cancel",
)


def register_browser_login_card_actions() -> None:
    for action_type in _ACTIONS:
        dispatcher.register(action_type, _handle_browser_login)


async def _handle_browser_login(payload: FeishuCardActionPayload) -> dict[str, Any]:
    action_type = _action_type(payload)
    values = _values(payload)
    session_id = values.get("session_id", "") or browser_login_manager.session_for_message(
        payload.open_message_id
    )
    if not session_id:
        return {"toast": {"type": "error", "content": "登录会话缺失或已过期"}}
    accepted = await browser_login_manager.submit(action_type, session_id, values)
    if not accepted:
        return {"toast": {"type": "error", "content": "登录会话已过期，请重新发起任务"}}
    return {"toast": {"type": "info", "content": "已提交"}}


def _action_type(payload: FeishuCardActionPayload) -> str:
    value = payload.action.value
    return value.action_type or str(getattr(value, "action", "") or "")


def _values(payload: FeishuCardActionPayload) -> dict[str, str]:
    data: dict[str, Any] = {}
    data.update(payload.action.value.model_dump())
    data.update(payload.action.form_value)
    data.update(payload.action.input_values)
    for name in ("formValue", "inputValues"):
        nested = getattr(payload.action, name, None)
        if isinstance(nested, dict):
            data.update(nested)
    return {str(key): str(value) for key, value in data.items() if value is not None}


__all__ = ["register_browser_login_card_actions"]
