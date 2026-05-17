from __future__ import annotations

import json
from typing import Any

from backend.common.logging import get_logger
from backend.common.types import AgentEvent
from backend.core.s01_agent_loop import AgentLoop, PlanExecuteRunner

logger = get_logger(component="feishu_tool_approval")


def attach_feishu_loop_approval(handler: Any, chat_id: str, loop: AgentLoop) -> None:
    if getattr(loop, "_feishu_tool_approval_attached", False):
        return
    register = getattr(loop, "on", None)
    if not callable(register):
        return

    async def on_event(event: AgentEvent) -> None:
        if event.type != "tool_approval_required":
            return
        await send_tool_approval_card(handler, chat_id, loop, event.data)

    register(on_event)
    setattr(loop, "_feishu_tool_approval_attached", True)


def attach_feishu_runner_approval(
    handler: Any,
    chat_id: str,
    runner: PlanExecuteRunner,
) -> None:
    if getattr(runner, "_feishu_tool_approval_attached", False):
        return
    original_build = runner._build_step_loop

    def build_step_loop(todo_step: object, context: object) -> AgentLoop:
        loop = original_build(todo_step, context)
        attach_feishu_loop_approval(handler, chat_id, loop)
        return loop

    runner._build_step_loop = build_step_loop
    setattr(runner, "_feishu_tool_approval_attached", True)


async def send_tool_approval_card(
    handler: Any,
    chat_id: str,
    loop: AgentLoop,
    data: object,
) -> None:
    try:
        if not isinstance(data, dict):
            return
        calls = [call for call in data.get("tool_calls", []) if isinstance(call, dict)]
        if not calls:
            return
        card = build_tool_approval_card(
            calls,
            chat_id=chat_id,
            owner_id=getattr(loop, "_owner_id", ""),
            session_id=getattr(loop._config, "session_id", ""),
        )
        await handler._client.send_card(chat_id, card)
    except Exception:
        logger.exception("feishu_tool_approval_card_failed", chat_id=chat_id)


def build_tool_approval_card(
    calls: list[dict[str, Any]],
    chat_id: str,
    owner_id: str,
    session_id: str,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    for call in calls:
        elements.append({"tag": "markdown", "content": _call_markdown(call)})
        elements.append(
            {
                "tag": "action",
                "actions": [
                    _button("同意", "primary", "tool_approve", call, chat_id, owner_id, session_id),
                    _button("拒绝", "danger", "tool_reject", call, chat_id, owner_id, session_id),
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "工具调用需要确认"},
            "template": "orange",
        },
        "elements": elements,
    }


def build_tool_status_card(tool_name: str, status_text: str) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "工具调用审批"},
            "template": "green" if status_text == "已同意" else "red",
        },
        "elements": [{"tag": "markdown", "content": f"**{tool_name or 'tool'}** {status_text}"}],
    }


def _call_markdown(call: dict[str, Any]) -> str:
    name = str(call.get("name", "tool"))
    reason = str(call.get("approval_reason", "") or "")
    args = json.dumps(call.get("arguments", {}), ensure_ascii=False, sort_keys=True)
    if len(args) > 800:
        args = args[:797] + "..."
    lines = [f"**{name}**", f"`{args}`"]
    if reason:
        lines.append(f"审核意见：{reason}")
    return "\n".join(lines)


def _button(
    label: str,
    button_type: str,
    action: str,
    call: dict[str, Any],
    chat_id: str,
    owner_id: str,
    session_id: str,
) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": button_type,
        "value": {
            "action": action,
            "action_type": action,
            "tool_call_id": str(call.get("id", "")),
            "tool_name": str(call.get("name", "")),
            "chat_id": chat_id,
            "owner_id": owner_id,
            "session_id": session_id,
        },
    }


__all__ = [
    "attach_feishu_loop_approval",
    "attach_feishu_runner_approval",
    "build_tool_approval_card",
    "build_tool_status_card",
    "send_tool_approval_card",
]
