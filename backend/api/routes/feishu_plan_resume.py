from __future__ import annotations

import asyncio
from typing import Any

from backend.core.s01_agent_loop import PlanCheckpointStore, PlanState
from backend.core.s01_agent_loop.plan_state_machine import TERMINAL_PHASES

from .feishu_plan_renderer import FeishuPlanRenderer
from .feishu_plan_runtime import FeishuPlanRunnerInput, create_feishu_resume_runner
from .feishu_plan_support import resume_plan, send_chat_text
from .feishu_tool_approval import attach_feishu_runner_approval

CONTINUE_TEXT = "继续"
DISCARD_TEXT = "放弃"


async def handle_plan_resume_gate(
    handler: Any,
    open_id: str,
    chat_id: str,
    text: str,
) -> bool:
    if chat_id in handler._plan_runners:
        return False
    pending = handler._pending_resume.get(open_id)
    if pending is not None:
        return await _handle_resume_decision(handler, open_id, chat_id, text, pending)
    state = _latest_incomplete_for_owner(open_id)
    if state is None:
        return False
    if text.strip() in {CONTINUE_TEXT, DISCARD_TEXT}:
        return await _handle_resume_decision(handler, open_id, chat_id, text, state)
    handler._pending_resume[open_id] = state
    await _send_resume_prompt(handler, chat_id, state)
    return True


async def _handle_resume_decision(
    handler: Any,
    open_id: str,
    chat_id: str,
    text: str,
    state: PlanState,
) -> bool:
    stripped = text.strip()
    if stripped == CONTINUE_TEXT:
        handler._pending_resume.pop(open_id, None)
        await _start_resume(handler, open_id, chat_id)
        return True
    if stripped == DISCARD_TEXT:
        handler._pending_resume.pop(open_id, None)
        PlanCheckpointStore().delete(state.session_id, state.plan_name)
        await handler._menu_state.clear_mode(open_id)
        await send_chat_text(handler, chat_id, "已放弃未完成的计划，并已切回普通模式。")
        return True
    await _send_resume_prompt(handler, chat_id, state)
    return True


async def _start_resume(handler: Any, open_id: str, chat_id: str) -> None:
    checkpoint_store = PlanCheckpointStore()
    renderer = FeishuPlanRenderer(
        handler._client,
        chat_id,
        owner_id=open_id,
        session_id=f"feishu-{chat_id}",
    )
    runner = await create_feishu_resume_runner(
        FeishuPlanRunnerInput(
            provider_manager=handler._pm,
            chat_id=chat_id,
            renderer=renderer,
            agent_runtime=handler._agent_runtime,
            task_queue=handler._task_queue,
            owner_id=open_id,
        ),
        checkpoint_store,
    )
    if runner is None:
        await send_chat_text(handler, chat_id, "未找到可恢复的计划。")
        return
    attach_feishu_runner_approval(handler, chat_id, runner)
    handler._plan_runners[chat_id] = runner
    asyncio.create_task(resume_plan(handler, chat_id, runner))


async def _send_resume_prompt(handler: Any, chat_id: str, state: PlanState) -> None:
    step_id = state.current_step_id or _first_incomplete_step_id(state)
    await send_chat_text(
        handler,
        chat_id,
        f"你有一个未完成的计划「{state.plan_name}」（中断于第 {step_id} 步）。"
        "回复「继续」恢复执行，或回复「放弃」清除。",
    )


def _latest_incomplete_for_owner(owner_id: str) -> PlanState | None:
    states = [
        state
        for state in PlanCheckpointStore().find_incomplete_by_owner(owner_id)
        if state.phase not in TERMINAL_PHASES
    ]
    if not states:
        return None
    return max(states, key=lambda state: state.updated_at)


def _first_incomplete_step_id(state: PlanState) -> int:
    for step in getattr(state.todo, "steps", []) or []:
        if step.status in {"running", "pending"}:
            return step.id
    return 0


__all__ = ["handle_plan_resume_gate"]
