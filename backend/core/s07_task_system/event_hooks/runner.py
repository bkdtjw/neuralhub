from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel

from .assess import AssessFn, HookVerdict, assess_hook
from .dedupe import dedupe_signals, visible_verdict
from .models import EventHook, HookState, HookStatus
from .retrieval_exa import ExaSearchFn, retrieve_exa
from .retrieval import TwitterSearchFn, retrieve_twitter
from .runner_state import (
    CADENCE_ESCALATING,
    CADENCE_RESOLVED,
    CADENCE_STABLE,
    PUSH_COOLDOWN_MINUTES,
    adaptive_cadence,
    next_state,
    scan_health,
    should_push,
    utc_now,
)
from .store import HookStore

PushFn = Callable[[EventHook, HookVerdict], Awaitable[None]]
NowFn = Callable[[], str]

# per-hook 互斥锁：调度器 tick 与手动扫描共享同一把锁，run_hook 全程持锁串行化，
# 避免长序列 读state→append_timeline→push(慢)→save_state 交错导致时间线丢更新 + 双推送。
_HOOK_LOCKS: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class HookRunError(Exception):
    ...


class RunOutcome(BaseModel):
    hook_id: str
    decision: Literal["push", "soft", "drop", "skipped"]
    turning_score: int
    status: HookStatus
    pushed: bool
    new_count: int
    next_cadence_minutes: int


async def run_hook(
    hook: EventHook,
    store: HookStore,
    *,
    twitter_search_fn: TwitterSearchFn,
    assess_fn: AssessFn,
    push_fn: PushFn,
    exa_search_fn: ExaSearchFn | None = None,
    now_fn: NowFn = utc_now,
) -> RunOutcome:
    try:
        if not hook.enabled:
            return _skipped_outcome(hook.id)
        async with _HOOK_LOCKS[hook.id]:
            return await _run_hook_locked(
                hook,
                store,
                twitter_search_fn=twitter_search_fn,
                assess_fn=assess_fn,
                push_fn=push_fn,
                exa_search_fn=exa_search_fn,
                now_fn=now_fn,
            )
    except HookRunError:
        raise
    except Exception as exc:
        raise HookRunError(f"HOOK_RUN_ERROR: {exc}") from exc


async def _run_hook_locked(
    hook: EventHook,
    store: HookStore,
    *,
    twitter_search_fn: TwitterSearchFn,
    assess_fn: AssessFn,
    push_fn: PushFn,
    exa_search_fn: ExaSearchFn | None,
    now_fn: NowFn,
) -> RunOutcome:
    prev_state = await store.get_state(hook.id)
    scanned_sources: list[str] = ["twitter"] if hook.sources.twitter else []
    signals = await retrieve_twitter(hook, twitter_search_fn) if hook.sources.twitter else []
    if exa_search_fn is not None and hook.sources.exa_web:
        signals = [*signals, *await retrieve_exa(hook, exa_search_fn)]
        scanned_sources.append("exa")
    signals = dedupe_signals(signals)
    if not signals:
        return await _empty_outcome(hook, store, prev_state, scanned_sources, now_fn())
    verdict = visible_verdict(await assess_hook(hook, signals, prev_state, assess_fn), prev_state)
    entries = verdict.new_entries
    current_state = prev_state
    if entries:
        current_state = await store.append_timeline(hook.id, entries)

    now = now_fn()
    state = next_state(hook.id, prev_state, current_state, verdict, now, scanned_sources)
    pushed = False
    if should_push(verdict, prev_state, now):
        try:
            await push_fn(hook, verdict)
            pushed = True
        except Exception:
            pushed = False
    if pushed:
        state = state.model_copy(update={"last_pushed_ts": now}, deep=True)
    await store.save_state(hook.id, state)

    return RunOutcome(
        hook_id=hook.id,
        decision=verdict.decision,
        turning_score=verdict.turning_score,
        status=verdict.status,
        pushed=pushed,
        new_count=len(entries),
        next_cadence_minutes=adaptive_cadence(verdict.status, hook.cadence_minutes),
    )


async def _empty_outcome(
    hook: EventHook,
    store: HookStore,
    prev_state: HookState | None,
    scanned_sources: list[str],
    now: str,
) -> RunOutcome:
    status = prev_state.status if prev_state else "stable"
    score = prev_state.confidence if prev_state else 0
    base = prev_state or HookState(hook_id=hook.id)
    update = {
        "hook_id": hook.id,
        "last_scanned": now,
        "source_health": scan_health(scanned_sources, base.source_health, now),
    }
    await store.save_state(hook.id, base.model_copy(update=update, deep=True))
    return RunOutcome(
        hook_id=hook.id, decision="drop", turning_score=score, status=status,
        pushed=False, new_count=0,
        next_cadence_minutes=adaptive_cadence(status, hook.cadence_minutes),
    )


def _skipped_outcome(hook_id: str) -> RunOutcome:
    return RunOutcome(
        hook_id=hook_id,
        decision="skipped",
        turning_score=0,
        status="stable",
        pushed=False,
        new_count=0,
        next_cadence_minutes=CADENCE_RESOLVED,
    )


__all__ = ["CADENCE_ESCALATING", "CADENCE_RESOLVED", "CADENCE_STABLE", "HookRunError",
           "NowFn", "PUSH_COOLDOWN_MINUTES", "PushFn", "RunOutcome", "adaptive_cadence", "run_hook"]
