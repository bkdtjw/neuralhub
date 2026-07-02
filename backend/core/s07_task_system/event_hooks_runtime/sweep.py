from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.common.logging import get_logger
from backend.core.s07_task_system.event_hooks import (
    PUSH_COOLDOWN_MINUTES,
    EventHook,
    HookState,
    HookStore,
    HookVerdict,
    hook_lock,
)
from backend.core.s07_task_system.event_hooks_runtime import HookRuntime, HookRuntimeError

logger = get_logger(component="event_hooks_sweep")

_DIGEST_TIMELINE = 3


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def sweep_pending_pushes(
    store: HookStore,
    runtime: HookRuntime,
    *,
    now_fn: Callable[[], str] = _utc_now,
) -> int:
    # 冷却期被拦下的重大进展会置 pending_push；本函数每 tick 廉价补推：冷却过后从现有 state
    # 构造摘要卡投递。best-effort：单个钩子失败不中断遍历，保持 pending 下轮再试。
    try:
        now_iso = now_fn()
        summaries = await store.list_summaries()
    except Exception as exc:  # noqa: BLE001
        raise HookRuntimeError(f"HOOK_SWEEP_PENDING_ERROR: {exc}") from exc

    delivered = 0
    for summary in summaries:
        if not _pending_due(summary.state, now_iso):
            continue
        if await _deliver_pending(store, runtime, summary.hook, now_iso):
            delivered += 1
    return delivered


async def _deliver_pending(
    store: HookStore, runtime: HookRuntime, hook: EventHook, now_iso: str,
) -> bool:
    # 持同一把 per-hook 锁与 run_hook 串行；锁内重取 state 复核，避免与并发扫描 TOCTOU。
    try:
        async with hook_lock(hook.id):
            state = await store.get_state(hook.id)
            if not _pending_due(state, now_iso) or state is None:
                return False
            await runtime.push_fn(hook, _digest_verdict(state))
            cleared = state.model_copy(
                update={"pending_push": False, "last_pushed_ts": now_iso}, deep=True)
            await store.save_state(hook.id, cleared)
            return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("event_hook_sweep_deliver_failed", hook_id=hook.id, error=str(exc))
        return False


def _pending_due(state: HookState | None, now_iso: str) -> bool:
    if state is None or not state.pending_push:
        return False
    return _minutes_since(state.last_pushed_ts, now_iso) >= PUSH_COOLDOWN_MINUTES


def _digest_verdict(state: HookState) -> HookVerdict:
    entries = state.timeline[:_DIGEST_TIMELINE]
    return HookVerdict(
        turning_score=state.confidence,
        numeric=0.0,
        materiality=state.confidence,
        status=state.status,
        decision="push",
        summary=state.summary,
        new_entries=[entry.model_copy(deep=True) for entry in entries],
    )


def _minutes_since(last_iso: str, now_iso: str) -> float:
    try:
        return (_parse_iso(now_iso) - _parse_iso(last_iso)).total_seconds() / 60
    except Exception:  # noqa: BLE001
        return 1_000_000_000


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["sweep_pending_pushes"]
