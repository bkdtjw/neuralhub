from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from .assess import AssessFn, HookVerdict, assess_hook
from .dedupe import dedupe_signals, visible_verdict
from .models import EventHook, HookState, HookStatus, SourceHealth
from .retrieval_exa import ExaSearchFn, retrieve_exa
from .retrieval import TwitterSearchFn, retrieve_twitter
from .store import HookStore

CADENCE_ESCALATING = 8
CADENCE_STABLE = 180
CADENCE_RESOLVED = 0
PUSH_COOLDOWN_MINUTES = 30

PushFn = Callable[[EventHook, HookVerdict], Awaitable[None]]
NowFn = Callable[[], str]


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


def adaptive_cadence(status: HookStatus, base_minutes: int) -> int:
    return CADENCE_RESOLVED if status == "resolved" else base_minutes


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def run_hook(
    hook: EventHook,
    store: HookStore,
    *,
    twitter_search_fn: TwitterSearchFn,
    assess_fn: AssessFn,
    push_fn: PushFn,
    exa_search_fn: ExaSearchFn | None = None,
    now_fn: NowFn = _utc_now,
) -> RunOutcome:
    try:
        if not hook.enabled:
            return RunOutcome(
                hook_id=hook.id,
                decision="skipped",
                turning_score=0,
                status="stable",
                pushed=False,
                new_count=0,
                next_cadence_minutes=CADENCE_RESOLVED,
            )

        prev_state = await store.get_state(hook.id)
        scanned_sources: list[str] = ["twitter"] if hook.sources.twitter else []
        signals = await retrieve_twitter(hook, twitter_search_fn) if hook.sources.twitter else []
        if exa_search_fn is not None and hook.sources.exa_web:
            signals = [*signals, *await retrieve_exa(hook, exa_search_fn)]
            scanned_sources.append("exa")
        signals = dedupe_signals(signals)
        if not signals:
            now = now_fn()
            status = prev_state.status if prev_state else "stable"
            score = prev_state.confidence if prev_state else 0
            base = prev_state or HookState(hook_id=hook.id)
            update = {"hook_id": hook.id, "last_scanned": now,
                      "source_health": _scan_health(scanned_sources, base.source_health, now)}
            await store.save_state(hook.id, base.model_copy(update=update, deep=True))
            return RunOutcome(
                hook_id=hook.id, decision="drop", turning_score=score, status=status,
                pushed=False, new_count=0,
                next_cadence_minutes=adaptive_cadence(status, hook.cadence_minutes),
            )
        verdict = visible_verdict(await assess_hook(hook, signals, prev_state, assess_fn), prev_state)
        entries = verdict.new_entries
        current_state = prev_state
        if entries:
            current_state = await store.append_timeline(hook.id, entries)

        now = now_fn()
        state = _next_state(hook.id, prev_state, current_state, verdict, now, scanned_sources)
        pushed = False
        if _should_push(verdict, prev_state, now):
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
    except HookRunError:
        raise
    except Exception as exc:
        raise HookRunError(f"HOOK_RUN_ERROR: {exc}") from exc


def _next_state(
    hook_id: str,
    prev_state: HookState | None,
    current_state: HookState | None,
    verdict: HookVerdict,
    now: str,
    scanned_sources: list[str],
) -> HookState:
    base = current_state or prev_state or HookState(hook_id=hook_id)
    prev_summary = prev_state.summary if prev_state else ""
    return base.model_copy(
        update={
            "hook_id": hook_id,
            "confidence": verdict.turning_score,
            "status": verdict.status,
            "summary": verdict.summary or prev_summary or "尚未扫描",
            "source_health": _scan_health(scanned_sources, base.source_health, now),
            "last_scanned": now,
        },
        deep=True,
    )


def _scan_health(scanned_sources: list[str], health: list[SourceHealth], now: str) -> list[SourceHealth]:
    # 只标记本轮真正扫过的源；关闭的源不能被标成"正常"
    updated = [item.model_copy(deep=True) for item in health]
    for source in scanned_sources:
        updated = _mark_health(updated, source, True, now)
    return updated


def _mark_health(
    health: list[SourceHealth],
    source: str,
    online: bool,
    now: str,
) -> list[SourceHealth]:
    updated: list[SourceHealth] = []
    found = False
    for item in health:
        if item.source == source:
            found = True
            updated.append(item.model_copy(update=_health_update(online, now), deep=True))
        else:
            updated.append(item.model_copy(deep=True))
    if not found:
        updated.append(SourceHealth(source=source, **_health_update(online, now)))
    return updated


def _health_update(online: bool, now: str) -> dict[str, str | bool]:
    update: dict[str, str | bool] = {"online": online}
    if online:
        update["last_ok"] = now
    return update


def _should_push(
    verdict: HookVerdict,
    prev_state: HookState | None,
    now: str,
) -> bool:
    if verdict.decision != "push":
        return False
    last_pushed = prev_state.last_pushed_ts if prev_state else ""
    return _minutes_since(last_pushed, now) >= PUSH_COOLDOWN_MINUTES


def _minutes_since(last_iso: str, now_iso: str) -> float:
    try:
        return (_parse_iso(now_iso) - _parse_iso(last_iso)).total_seconds() / 60
    except Exception:
        return 1_000_000_000


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["CADENCE_ESCALATING", "CADENCE_RESOLVED", "CADENCE_STABLE", "HookRunError",
           "NowFn", "PUSH_COOLDOWN_MINUTES", "PushFn", "RunOutcome", "adaptive_cadence", "run_hook"]
