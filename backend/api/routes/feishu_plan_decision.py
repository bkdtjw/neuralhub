from __future__ import annotations

from typing import Any

from backend.core.s01_agent_loop import (
    PlanCheckpointStore,
    PlanControlStore,
    PlanPhase,
    TERMINAL_PHASES,
)


def approve_plan_decision(handler: Any, chat_id: str, plan_name: str, owner_id: str) -> bool:
    runner = find_plan_runner(handler._plan_runners, chat_id, plan_name)
    if runner is not None and owner_matches(runner, owner_id):
        runner.approve()
        return True
    return _request_checkpoint_decision(chat_id, plan_name, owner_id, "approve")


def reject_plan_decision(handler: Any, chat_id: str, plan_name: str, owner_id: str) -> bool:
    runner = find_plan_runner(handler._plan_runners, chat_id, plan_name)
    if runner is not None and owner_matches(runner, owner_id):
        runner.reject("Plan rejected from Feishu")
        return True
    return _request_checkpoint_decision(chat_id, plan_name, owner_id, "reject")


def cancel_plan_decision(handler: Any, chat_id: str, plan_name: str) -> bool:
    runner = find_plan_runner(handler._plan_runners, chat_id, plan_name)
    if runner is not None:
        runner.cancel()
        return True
    return _request_checkpoint_decision(chat_id, plan_name, "", "stop")


def find_plan_runner(runners: dict[str, Any], chat_id: str, plan_name: str) -> Any | None:
    runner = runners.get(chat_id)
    if runner is not None:
        return runner
    if not plan_name:
        return None
    return next((item for item in runners.values() if item.plan_name == plan_name), None)


def owner_matches(target: Any, owner_id: str) -> bool:
    actual = str(getattr(target, "_owner_id", "") or "")
    return not owner_id or not actual or actual == owner_id


def _request_checkpoint_decision(
    chat_id: str,
    plan_name: str,
    owner_id: str,
    action: str,
) -> bool:
    state = PlanCheckpointStore().load_latest(f"feishu-{chat_id}")
    if state is None or state.phase in TERMINAL_PHASES:
        return False
    if plan_name and state.plan_name != plan_name:
        return False
    if owner_id and state.owner_id and state.owner_id != owner_id:
        return False
    store = PlanControlStore()
    if action == "approve":
        if state.phase in {PlanPhase.EXECUTING, PlanPhase.PAUSED}:
            return True
        if state.phase not in {PlanPhase.PLAN_READY, PlanPhase.AWAITING_APPROVAL}:
            return False
        store.request_approve(state.session_id)
        return True
    if action == "reject":
        if state.phase in {PlanPhase.PLAN_READY, PlanPhase.AWAITING_APPROVAL}:
            store.request_reject(state.session_id, "Plan rejected from Feishu")
        else:
            store.request_stop(state.session_id)
        return True
    if action == "stop":
        store.request_stop(state.session_id)
        return True
    return False


__all__ = [
    "approve_plan_decision",
    "cancel_plan_decision",
    "find_plan_runner",
    "owner_matches",
    "reject_plan_decision",
]
