from __future__ import annotations

from typing import Any

from backend.common.logging import get_logger
from backend.core.s01_agent_loop import (
    PlanCheckpointStore,
    PlanControlStore,
    PlanPhase,
    TERMINAL_PHASES,
    UserConfigStore,
)

logger = get_logger(component="feishu_plan_control")

PAUSE_REPLY = "已暂停后续步骤。补充要求请直接回复；不补充请回复「继续」。"
STOP_REPLY = "已停止当前计划，后续步骤不会继续执行。"
RESUME_REPLY = "已继续执行当前计划。"
INSTRUCTION_REPLY = "已收到补充要求，将继续执行后续步骤。"
NO_PLAN_REPLY = "当前没有正在执行的计划。"
RUNNING_REPLY = "正在执行计划，可通过菜单「计划控制 → 暂停/停止」处理。"
AUTO_APPROVE_ON_REPLY = (
    "MCP 工具自动审批已开启。\n"
    "工具调用将由 LLM 审核，仅不安全的操作会请求你确认。"
)
AUTO_APPROVE_OFF_REPLY = (
    "MCP 工具自动审批已关闭。\n"
    "所有 MCP 工具调用都将请求你手动确认。"
)


async def pause_plan_from_menu(handler: Any, open_id: str) -> None:
    try:
        chat_id = await handler._menu_state.get_chat(open_id)
        runner = handler._plan_runners.get(chat_id)
        if not chat_id or (runner is None and not _has_active_plan(chat_id)):
            await handler._send_to_user(open_id, NO_PLAN_REPLY)
            return
        if runner is not None:
            runner.pause()
        else:
            PlanControlStore().request_pause(_session_id(chat_id))
        await handler._send_to_user(open_id, PAUSE_REPLY)
    except Exception:
        logger.exception("feishu_plan_pause_failed", open_id=open_id)


async def stop_plan_from_menu(handler: Any, open_id: str) -> None:
    try:
        chat_id = await handler._menu_state.get_chat(open_id)
        if not chat_id or not await stop_active_plan_for_chat(handler, chat_id):
            await handler._send_to_user(open_id, NO_PLAN_REPLY)
            return
        await handler._send_to_user(open_id, STOP_REPLY)
    except Exception:
        logger.exception("feishu_plan_stop_failed", open_id=open_id)


async def stop_active_plan_for_chat(handler: Any, chat_id: str) -> bool:
    try:
        if not chat_id or not has_active_plan(handler, chat_id):
            return False
        runner = handler._plan_runners.get(chat_id)
        if runner is not None:
            runner.cancel()
        PlanControlStore().request_stop(_session_id(chat_id))
        return True
    except Exception:
        logger.exception("feishu_plan_stop_chat_failed", chat_id=chat_id)
        return False


async def toggle_auto_approve_from_menu(handler: Any, open_id: str) -> None:
    try:
        store = UserConfigStore()
        config = store.get(open_id)
        config.auto_approve_tools = not config.auto_approve_tools
        store.save(config)
        reply = AUTO_APPROVE_ON_REPLY if config.auto_approve_tools else AUTO_APPROVE_OFF_REPLY
        await handler._send_to_user(open_id, reply)
    except Exception:
        logger.exception("feishu_auto_approve_toggle_failed", open_id=open_id)


async def handle_plan_control_message(handler: Any, chat_id: str, text: str) -> bool:
    runner = handler._plan_runners.get(chat_id)
    remote_active = runner is None and _has_active_plan(chat_id)
    if runner is None:
        if not remote_active:
            return False
    text = text.strip()
    if text == "停止":
        if runner is not None:
            runner.cancel()
        PlanControlStore().request_stop(_session_id(chat_id))
        await handler._send_chat_text(chat_id, STOP_REPLY)
        return True
    if runner is None:
        return await _handle_remote_message(handler, chat_id, text)
    if not _runner_paused(runner):
        return False
    if text == "继续":
        runner.resume()
        await handler._send_chat_text(chat_id, RESUME_REPLY)
        return True
    if text:
        runner.resume(text)
        await handler._send_chat_text(chat_id, INSTRUCTION_REPLY)
        return True
    await handler._send_chat_text(chat_id, PAUSE_REPLY)
    return True


def has_active_plan(handler: Any, chat_id: str) -> bool:
    return chat_id in handler._plan_runners or _has_active_plan(chat_id)


async def _handle_remote_message(handler: Any, chat_id: str, text: str) -> bool:
    if not _is_paused_plan(chat_id):
        return False
    if text == "继续":
        PlanControlStore().request_resume(_session_id(chat_id))
        await handler._send_chat_text(chat_id, RESUME_REPLY)
        return True
    if text:
        PlanControlStore().request_resume(_session_id(chat_id), text)
        await handler._send_chat_text(chat_id, INSTRUCTION_REPLY)
        return True
    await handler._send_chat_text(chat_id, PAUSE_REPLY)
    return True


def _runner_paused(runner: Any) -> bool:
    is_paused = getattr(runner, "is_paused", None)
    if callable(is_paused):
        return bool(is_paused())
    return False


def _has_active_plan(chat_id: str) -> bool:
    state = PlanCheckpointStore().load_latest(_session_id(chat_id))
    return state is not None and state.phase not in TERMINAL_PHASES


def _is_paused_plan(chat_id: str) -> bool:
    state = PlanCheckpointStore().load_latest(_session_id(chat_id))
    return state is not None and state.phase == PlanPhase.PAUSED


def _session_id(chat_id: str) -> str:
    return f"feishu-{chat_id}"


__all__ = [
    "handle_plan_control_message",
    "has_active_plan",
    "pause_plan_from_menu",
    "stop_active_plan_for_chat",
    "stop_plan_from_menu",
    "toggle_auto_approve_from_menu",
]
