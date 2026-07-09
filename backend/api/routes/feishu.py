"""Feishu event callback route for bidirectional communication."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from fastapi import APIRouter, Request

from backend.common.logging import bound_log_context, get_logger, new_trace_id

from .feishu_signature_support import request_signature_ok

logger = get_logger(component="feishu_route")

router = APIRouter(prefix="/api/feishu", tags=["feishu"])

_handler: Any = None
_background_tasks: set[asyncio.Task[Any]] = set()


def set_handler(handler: Any) -> None:
    global _handler  # noqa: PLW0603
    _handler = handler


def _log_task_exception(task: asyncio.Task[Any]) -> None:
    # 回收 fire-and-forget 任务的强引用，并检索异常，避免未捕获异常被 asyncio 默认 handler 静默吞掉。
    _background_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "feishu_handle_message_task_failed",
            error=str(error),
            error_type=type(error).__name__,
        )


def _nested_str(data: dict[str, Any], *keys: str) -> str:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current if isinstance(current, str) else ""


def _card_action_payload_data(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("action"):
        return data
    event = data.get("event")
    if not isinstance(event, dict) or not event.get("action"):
        return None
    open_id = _nested_str(event, "operator", "operator_id", "open_id") or _nested_str(
        event, "operator", "open_id"
    )
    return {
        "open_id": open_id,
        "open_message_id": _nested_str(event, "context", "open_message_id"),
        "open_chat_id": _nested_str(event, "context", "open_chat_id"),
        "token": _nested_str(event, "token"),
        "action": event.get("action", {}),
    }


@router.post("/event")
async def feishu_event(request: Request) -> dict[str, Any]:
    body = await request.body()
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return {"error": "invalid json"}

    # URL verification challenge
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge", "")}

    event_id = data.get("header", {}).get("event_id", "")
    event_type = data.get("header", {}).get("event_type", "")
    chat_id = data.get("event", {}).get("message", {}).get("chat_id", "")

    # Signature verification (url_verification challenge above is handled first
    # on purpose: Feishu's callback-URL challenge may arrive unsigned).
    if not request_signature_ok(request, body):
        logger.warning("feishu_signature_invalid")
        return {}

    # Card action fallback: support both legacy root action and v2 event.action payloads.
    card_action_data = _card_action_payload_data(data)
    if card_action_data is not None:
        from backend.api.routes.feishu_card_action import dispatcher
        from backend.schemas.feishu import FeishuCardActionPayload

        try:
            payload = FeishuCardActionPayload.model_validate(card_action_data)
            result = await dispatcher.dispatch(payload)
            value = payload.action.value
            action_type = value.action_type or str(getattr(value, "action", "") or "")
            logger.info(
                "feishu_card_action_fallback_dispatched",
                action_type=action_type,
                plan_name=str(getattr(value, "plan_name", "") or ""),
                event_type=event_type,
                open_id=payload.open_id,
            )
            return result
        except Exception:
            logger.exception("feishu_card_action_fallback_failed")
            return {}

    if event_type == "application.bot.menu_v6":
        event = data.get("event", {})
        event_key = event.get("event_key", "")
        open_id = _nested_str(event, "operator", "operator_id", "open_id") or _nested_str(
            event, "operator", "open_id"
        )
        if await _seen_by_handler(event_id):
            return {"code": 0}
        if _handler is not None and open_id and event_key:
            await _handler.handle_menu_event(event_key, open_id)
        return {"code": 0}

    if event_type != "im.message.receive_v1":
        return {"status": "ignored"}

    with bound_log_context(trace_id=new_trace_id(), session_id=chat_id):
        logger.info("feishu_event_received", event_id=event_id, event_type=event_type)
        if _handler is not None:
            task = asyncio.create_task(_handler.handle_message(data))
            _background_tasks.add(task)
            task.add_done_callback(_log_task_exception)

    return {"status": "ok"}


async def _seen_by_handler(event_id: str) -> bool:
    if _handler is None or not event_id:
        return False
    seen = getattr(_handler, "_seen", None)
    if not callable(seen):
        return False
    result = seen(event_id)
    if not inspect.isawaitable(result):
        return False
    return bool(await result)
