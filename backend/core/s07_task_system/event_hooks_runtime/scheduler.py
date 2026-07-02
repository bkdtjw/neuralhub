from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from backend.common.logging import get_logger
from backend.core.s07_task_system.event_hooks import (
    HookStore,
    HookSummary,
    RunOutcome,
    adaptive_cadence,
    mark_scan_failed,
    run_hook,
)
from backend.core.s07_task_system.event_hooks_runtime import HookRuntime, HookRuntimeError
from backend.core.s07_task_system.event_hooks_runtime.sweep import sweep_pending_pushes

logger = get_logger(component="event_hooks_scheduler")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def is_due(summary: HookSummary, now_iso: str) -> bool:
    if summary.hook.enabled is False:
        return False
    state = summary.state
    status = state.status if state else "developing"
    cadence = adaptive_cadence(status, summary.hook.cadence_minutes)
    if cadence <= 0:
        return False
    if state is None or not state.last_scanned:
        return True
    return _minutes_since(state.last_scanned, now_iso) >= cadence


async def scan_due_hooks(
    store: HookStore,
    runtime: HookRuntime,
    *,
    now_fn: Callable[[], str] = _utc_now,
) -> list[RunOutcome]:
    try:
        now_iso = now_fn()
        summaries = await store.list_summaries()
    except Exception as exc:  # noqa: BLE001
        raise HookRuntimeError(f"HOOK_SCAN_DUE_ERROR: {exc}") from exc

    outcomes: list[RunOutcome] = []
    for summary in summaries:
        try:
            if not is_due(summary, now_iso):
                continue
            outcome = await run_hook(
                summary.hook,
                store,
                twitter_search_fn=runtime.twitter_search_fn,
                assess_fn=runtime.assess_fn,
                push_fn=runtime.push_fn,
                exa_search_fn=runtime.exa_search_fn,
            )
            outcomes.append(outcome)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "event_hook_scan_failed",
                hook_id=summary.hook.id,
                error=str(exc),
            )
            await _mark_failed_best_effort(store, summary.hook.id, now_iso)
    return outcomes


async def _mark_failed_best_effort(store: HookStore, hook_id: str, now_iso: str) -> None:
    # 失败也推进 last_scanned，避免每 60s tick 无限重试烧配额。
    # best-effort：自身异常也吞掉，不能让单个钩子的清理失败中断后续钩子遍历。
    try:
        await mark_scan_failed(hook_id, store, now_iso)
    except Exception as exc:  # noqa: BLE001
        logger.exception("event_hook_mark_failed_error", hook_id=hook_id, error=str(exc))


class HookScheduler:
    def __init__(
        self,
        store: HookStore,
        runtime: HookRuntime,
        *,
        tick_seconds: float = 60.0,
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._tick_seconds = tick_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            if self._running:
                return
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("event_hooks_scheduler_started", tick_seconds=self._tick_seconds)
        except Exception as exc:  # noqa: BLE001
            self._running = False
            raise HookRuntimeError(f"HOOK_SCHEDULER_START_ERROR: {exc}") from exc

    async def stop(self) -> None:
        try:
            self._running = False
            if self._task is not None:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    logger.debug("event_hooks_scheduler_cancelled")
                self._task = None
            logger.info("event_hooks_scheduler_stopped")
        except Exception as exc:  # noqa: BLE001
            raise HookRuntimeError(f"HOOK_SCHEDULER_STOP_ERROR: {exc}") from exc

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    await scan_due_hooks(self._store, self._runtime)
                    await sweep_pending_pushes(self._store, self._runtime)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("event_hooks_scheduler_tick_failed", error=str(exc))
                await asyncio.sleep(self._tick_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HookRuntimeError(f"HOOK_SCHEDULER_LOOP_ERROR: {exc}") from exc


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


__all__ = ["HookScheduler", "is_due", "scan_due_hooks"]
