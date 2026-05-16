from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from .plan_control_store import PlanControlStore
from .plan_execute_errors import PlanExecuteError
from .plan_models import PlanPhase

APPROVAL_POLL_SECONDS = 1.0


async def await_plan_approval(runner: Any) -> bool:
    if runner._plan is None:
        raise PlanExecuteError("PLAN_APPROVAL_PLAN_MISSING", "Missing plan")
    runner._approval_event.clear()
    if runner._state.phase != PlanPhase.AWAITING_APPROVAL:
        runner._set_phase(PlanPhase.AWAITING_APPROVAL)
    await runner._notify_renderer("on_plan_created", runner._plan, runner._plan_name)
    try:
        await _wait_for_approval_or_signal(runner)
    except TimeoutError:
        runner._state.error_message = f"审批超时（{runner._approval_timeout_seconds:.0f}秒）"
        runner._cancelled = True
        runner._persist_state()
    if runner._cancelled:
        runner._skip_from(0)
        runner._finish("cancelled")
        await runner._notify_finished()
        return False
    return True


async def _wait_for_approval_or_signal(runner: Any) -> None:
    store = PlanControlStore()
    deadline = monotonic() + runner._approval_timeout_seconds
    while not runner._cancelled:
        if _apply_approval_signal(runner, store):
            return
        if runner._approval_event.is_set():
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        try:
            await asyncio.wait_for(
                runner._approval_event.wait(),
                timeout=min(APPROVAL_POLL_SECONDS, remaining),
            )
        except TimeoutError:
            continue


def _apply_approval_signal(runner: Any, store: PlanControlStore) -> bool:
    signal = store.read(runner._session_id)
    if signal.action == "approve":
        store.clear(runner._session_id)
        runner._approval_event.set()
        return True
    if signal.action in {"reject", "stop"}:
        store.clear(runner._session_id)
        runner._state.error_message = signal.instruction or "Plan rejected by user"
        runner._cancelled = True
        runner._approval_event.set()
        return True
    return False


__all__ = ["await_plan_approval"]
