from __future__ import annotations

from typing import Any

from backend.schemas.feishu import FeishuCardActionPayload

from .feishu_tool_approval import build_tool_status_card


def _get_handler() -> Any:
    try:
        from backend.api.routes import feishu

        return getattr(feishu, "_handler", None)
    except Exception:
        return None


async def handle_plan_approve(payload: FeishuCardActionPayload) -> dict[str, Any]:
    value = payload.action.value
    plan_name = str(getattr(value, "plan_name", "") or "")
    chat_id = str(getattr(value, "chat_id", "") or getattr(payload, "open_chat_id", "") or "")
    owner_id = str(getattr(value, "owner_id", "") or "")
    if not _operator_allowed(payload, owner_id):
        return {"toast": {"type": "warning", "content": "无权审批该计划"}}
    handler = _get_handler()
    approved = bool(
        handler and getattr(handler, "approve_plan", lambda *_: False)(chat_id, plan_name, owner_id)
    )
    content = f"计划 {plan_name} 已批准，开始执行" if approved else f"计划 {plan_name} 未找到或已结束"
    return {"toast": {"type": "info" if approved else "warning", "content": content}}


async def handle_plan_cancel(payload: FeishuCardActionPayload) -> dict[str, Any]:
    value = payload.action.value
    plan_name = str(getattr(value, "plan_name", "") or "")
    chat_id = str(getattr(value, "chat_id", "") or getattr(payload, "open_chat_id", "") or "")
    owner_id = str(getattr(value, "owner_id", "") or "")
    if not _operator_allowed(payload, owner_id):
        return {"toast": {"type": "warning", "content": "无权审批该计划"}}
    handler = _get_handler()
    rejected = bool(
        handler and getattr(handler, "reject_plan", lambda *_: False)(chat_id, plan_name, owner_id)
    )
    cancelled = rejected or bool(
        handler and getattr(handler, "cancel_plan", lambda *_: False)(chat_id, plan_name)
    )
    content = f"计划 {plan_name} 已取消" if cancelled else f"计划 {plan_name} 未找到或已结束"
    return {"toast": {"type": "warning", "content": content}}


async def handle_tool_approve(payload: FeishuCardActionPayload) -> dict[str, Any]:
    return await _handle_tool_decision(payload, approved=True)


async def handle_tool_reject(payload: FeishuCardActionPayload) -> dict[str, Any]:
    return await _handle_tool_decision(payload, approved=False)


async def _handle_tool_decision(payload: FeishuCardActionPayload, approved: bool) -> dict[str, Any]:
    value = payload.action.value
    chat_id = str(getattr(value, "chat_id", "") or getattr(payload, "open_chat_id", "") or "")
    owner_id = str(getattr(value, "owner_id", "") or "")
    tool_call_id = str(getattr(value, "tool_call_id", "") or "")
    tool_name = str(getattr(value, "tool_name", "") or "")
    if not _operator_allowed(payload, owner_id):
        return {"toast": {"type": "warning", "content": "无权审批该工具调用"}}
    handler = _get_handler()
    resolved = bool(
        handler
        and getattr(handler, "resolve_tool_call", lambda *_: False)(
            chat_id, tool_call_id, approved, owner_id
        )
    )
    status = "已同意" if approved else "已拒绝"
    if not resolved:
        await _update_action_card(handler, payload.open_message_id, tool_name, "已超时")
        return {
            "toast": {"type": "warning", "content": "工具调用已超时或已处理"},
        }
    await _update_action_card(handler, payload.open_message_id, tool_name, status)
    return {
        "toast": {"type": "info", "content": f"工具调用{status}"},
    }


def _operator_allowed(payload: FeishuCardActionPayload, owner_id: str) -> bool:
    return not owner_id or not payload.open_id or payload.open_id == owner_id


async def _update_action_card(
    handler: Any,
    message_id: str,
    tool_name: str,
    status_text: str,
) -> None:
    client = getattr(handler, "_client", None)
    if not message_id or client is None:
        return
    update_card = getattr(client, "update_card", None)
    if not callable(update_card):
        return
    await update_card(message_id, build_tool_status_card(tool_name, status_text))


__all__ = [
    "handle_plan_approve",
    "handle_plan_cancel",
    "handle_tool_approve",
    "handle_tool_reject",
]
