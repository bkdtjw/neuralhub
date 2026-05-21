"""Card action callback route for Feishu interactive card buttons."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Request

from backend.common.logging import bound_log_context, get_logger, new_trace_id
from backend.config.settings import settings as app_settings
from backend.core.s07_task_system import TaskExecutionError
from backend.schemas.feishu import FeishuCardActionPayload

from .feishu_card_approval import (
    handle_plan_adjust,
    handle_plan_approve,
    handle_plan_cancel,
    handle_tool_approve,
    handle_tool_reject,
)

logger = get_logger(component="feishu_card_action")

router = APIRouter(prefix="/api/feishu", tags=["feishu"])


class CardActionDispatcher:
    """Dispatch card button callbacks by action_type."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Coroutine[Any, Any, dict]]] = {}

    def register(self, action_type: str, handler: Callable[..., Coroutine[Any, Any, dict]]) -> None:
        self._handlers[action_type] = handler

    async def dispatch(self, payload: FeishuCardActionPayload) -> dict[str, Any]:
        action_type = _action_type(payload)
        handler = self._handlers.get(action_type)
        if handler is None:
            return {}
        return await handler(payload)


dispatcher = CardActionDispatcher()

# Module-level executor reference, set during app lifespan.
_task_executor: Any = None


def set_task_executor(executor: Any) -> None:
    """Store TaskExecutor reference for card action handlers."""
    global _task_executor
    _task_executor = executor


def _action_type(payload: FeishuCardActionPayload) -> str:
    value = payload.action.value
    return value.action_type or str(getattr(value, "action", "") or "")


async def _handle_rerun(payload: FeishuCardActionPayload) -> dict[str, Any]:
    """Handle 'rerun' button click from task execution report card."""
    task_id: str | None = getattr(payload.action.value, "task_id", None)
    logger.info(
        "feishu_card_action",
        action_type="rerun",
        task_id=task_id or "",
        open_id=payload.open_id,
    )
    if not task_id:
        return {"toast": {"type": "error", "content": "缺少任务 ID"}}

    executor = _task_executor
    if executor is None:
        return {"toast": {"type": "error", "content": "服务未就绪，请稍后重试"}}

    try:
        from backend.core.s07_task_system.store import TaskStore

        store = TaskStore()
        task = await store.get_task(task_id)
        if task is None:
            return {"toast": {"type": "error", "content": f"任务 {task_id} 不存在"}}
        if not task.enabled:
            return {"toast": {"type": "error", "content": f"任务 {task.name} 已停用"}}

        asyncio.create_task(_background_rerun(task_id, task.name))
    except Exception:
        logger.exception("feishu_card_action_error", action_type="rerun", task_id=task_id)
        return {"toast": {"type": "error", "content": "加入执行队列失败"}}

    return {"toast": {"type": "info", "content": f"任务 {task.name} 已加入执行队列"}}


async def _background_rerun(task_id: str, task_name: str) -> None:
    """Execute a task in the background, triggered by card rerun button."""
    try:
        from backend.core.s07_task_system.store import TaskStore

        store = TaskStore()
        task = await store.get_task(task_id)
        if task is None:
            return
        result = await _task_executor.execute(task)
        await store.update_run_status(task_id, "success", result[:500])
        logger.info("feishu_card_rerun_completed", task_id=task_id, task_name=task_name)
    except TaskExecutionError as exc:
        logger.exception("feishu_card_rerun_failed", task_id=task_id, task_name=task_name)
        try:
            await store.update_run_status(task_id, "error", (exc.output or exc.message)[:500])
        except Exception:
            logger.exception("feishu_card_rerun_status_failed", task_id=task_id)
    except Exception:
        logger.exception("feishu_card_rerun_failed", task_id=task_id, task_name=task_name)
        try:
            await store.update_run_status(task_id, "error", "rerun failed")
        except Exception:
            logger.exception("feishu_card_rerun_status_failed", task_id=task_id)


# Register handlers
dispatcher.register("rerun", _handle_rerun)
dispatcher.register("plan_adjust", handle_plan_adjust)
dispatcher.register("plan_approve", handle_plan_approve)
dispatcher.register("plan_cancel", handle_plan_cancel)
dispatcher.register("tool_approve", handle_tool_approve)
dispatcher.register("tool_reject", handle_tool_reject)


def _verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    token = app_settings.feishu_verification_token
    if not token:
        return True
    string_to_sign = f"{timestamp}\n{token}"
    expected = hmac.new(
        string_to_sign.encode("utf-8"),
        body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/card_action")
async def card_action(request: Request) -> dict[str, Any]:
    return await _handle_card_action_request(request)


@router.post("/plan_approval")
async def plan_approval(request: Request) -> dict[str, Any]:
    return await _handle_card_action_request(request)


@router.post("/tool_approval")
async def tool_approval(request: Request) -> dict[str, Any]:
    return await _handle_card_action_request(request)


async def _handle_card_action_request(request: Request) -> dict[str, Any]:
    body = await request.body()
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return {}

    # Challenge verification (Feishu sends this when configuring callback URL)
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge", "")}

    # Signature verification
    timestamp = request.headers.get("X-Lark-Signature-Timestamp", "")
    signature = request.headers.get("X-Lark-Signature-Signature", "")
    if timestamp and signature:
        if not _verify_signature(body, timestamp, signature):
            logger.warning("feishu_signature_invalid")
            return {}

    try:
        payload = FeishuCardActionPayload.model_validate(data)
    except Exception:
        logger.warning("feishu_card_action_parse_failed")
        return {}

    with bound_log_context(trace_id=new_trace_id(), session_id=payload.open_id):
        result = await dispatcher.dispatch(payload)
        logger.info(
            "feishu_card_action_dispatched",
            action_type=_action_type(payload),
            open_id=payload.open_id,
        )
        return result


__all__ = ["CardActionDispatcher", "dispatcher", "router"]
