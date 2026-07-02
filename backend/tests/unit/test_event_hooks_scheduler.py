from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.s07_task_system import event_hooks as eh
from backend.core.s07_task_system.event_hooks_runtime import HookRuntime
from backend.core.s07_task_system.event_hooks_runtime.scheduler import (
    HookScheduler,
    is_due,
    scan_due_hooks,
)

pytestmark = pytest.mark.asyncio
NOW = "2026-06-27T02:00:00Z"


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


def _hook(enabled: bool = True, cadence_minutes: int = 45) -> eh.EventHook:
    return eh.EventHook(
        id="hook-1",
        name="Launch Watch",
        twitter=eh.HookTwitterConfig(accounts=["newsdesk"]),
        sources=eh.HookSources(),
        cadence_minutes=cadence_minutes,
        materiality=60,
        enabled=enabled,
        created_at="2026-06-27T00:00:00Z",
    )


def _summary(
    *,
    enabled: bool = True,
    status: eh.HookStatus = "developing",
    last_scanned: str = "",
) -> eh.HookSummary:
    state = eh.HookState(hook_id="hook-1", status=status, last_scanned=last_scanned)
    return eh.HookSummary(hook=_hook(enabled=enabled), state=state)


def _draft(name: str, enabled: bool = True) -> eh.HookDraft:
    return eh.HookDraft(
        name=name,
        twitter=eh.HookTwitterConfig(accounts=["newsdesk"]),
        sources=eh.HookSources(),
        cadence_minutes=45,
        materiality=60,
        enabled=enabled,
    )


def _tweet(author: str = "newsdesk") -> SimpleNamespace:
    return SimpleNamespace(
        author_name=author,
        author_handle=author,
        text="Launch window moved",
        likes=40,
        retweets=5,
        created_at="2026-06-27T01:00:00Z",
        url=f"https://x.com/{author}/status/1",
    )


def _runtime(calls: list[str]) -> HookRuntime:
    async def twitter_search_fn(query: eh.TwitterQuery) -> list[SimpleNamespace]:
        calls.append(f"search:{query.query}")
        return [_tweet()]

    async def assess_fn(request: eh.AssessRequest) -> eh.Assessment:
        calls.append(f"assess:{request.hook.name}")
        if request.hook.name == "Bad Due":
            raise RuntimeError("assessment failed")
        return eh.Assessment(
            materiality=90,
            summary="Confirmed",
            developments=[
                eh.Development(
                    text="Launch window moved",
                    ts="2026-06-27T01:00:00Z",
                    source="twitter",
                )
            ],
        )

    async def push_fn(hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        calls.append(f"push:{hook.name}:{verdict.decision}")

    async def exa_search_fn(query: eh.ExaQuery) -> list[SimpleNamespace]:
        calls.append(f"exa:{query.query}")
        return []

    return HookRuntime(
        twitter_search_fn=twitter_search_fn,
        assess_fn=assess_fn,
        push_fn=push_fn,
        exa_search_fn=exa_search_fn,
    )


async def _set_state(
    store: eh.HookStore,
    summary: eh.HookSummary,
    *,
    status: eh.HookStatus = "developing",
    last_scanned: str,
) -> None:
    state = await store.get_state(summary.hook.id)
    assert state is not None
    await store.save_state(
        summary.hook.id,
        state.model_copy(update={"status": status, "last_scanned": last_scanned}),
    )


async def test_is_due_branches() -> None:
    assert is_due(_summary(last_scanned=""), NOW) is True
    assert is_due(_summary(last_scanned="2026-06-27T01:50:00Z"), NOW) is False
    assert is_due(_summary(status="resolved", last_scanned=""), NOW) is False
    assert is_due(_summary(enabled=False, last_scanned=""), NOW) is False
    assert is_due(_summary(last_scanned="2026-06-27T01:00:00Z"), NOW) is True


async def test_scan_due_hooks_isolates_hook_failures(tmp_path: Path) -> None:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    good = await store.create(_draft("Good Due"))
    recent = await store.create(_draft("Recent"))
    bad = await store.create(_draft("Bad Due"))
    later = await store.create(_draft("Later Due"))
    await _set_state(store, good, last_scanned="2026-06-27T01:00:00Z")
    await _set_state(store, recent, last_scanned="2026-06-27T01:50:00Z")
    await _set_state(store, bad, last_scanned="2026-06-27T01:00:00Z")
    await _set_state(store, later, last_scanned="2026-06-27T01:00:00Z")
    calls: list[str] = []

    outcomes = await scan_due_hooks(store, _runtime(calls), now_fn=lambda: NOW)

    assert [outcome.hook_id for outcome in outcomes] == [good.hook.id, later.hook.id]
    assert all(outcome.decision == "push" for outcome in outcomes)
    assert f"assess:{recent.hook.name}" not in calls
    assert f"assess:{bad.hook.name}" in calls
    assert f"exa:{later.hook.name}" in calls
    assert f"push:{later.hook.name}:push" in calls


async def test_failed_scan_advances_last_scanned_and_not_due_next_tick(tmp_path: Path) -> None:
    # 缺陷 A：扫描失败也推进 last_scanned，避免每 60s tick 无限重试烧配额。
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    bad = await store.create(_draft("Bad Due"))
    # 上次扫描远早于 now（>cadence），故本轮 is_due=True。
    await _set_state(store, bad, last_scanned="2026-06-27T01:00:00Z")
    calls: list[str] = []

    outcomes = await scan_due_hooks(store, _runtime(calls), now_fn=lambda: NOW)

    # 该钩子失败（无 outcome），但 last_scanned 已推进到本轮 NOW。
    assert outcomes == []
    state = await store.get_state(bad.hook.id)
    assert state is not None
    assert state.last_scanned == NOW
    # 下个 tick（同一 NOW 甚至几分钟后）不再 due —— 按 cadence(45min) 退避重试。
    later_summary = eh.HookSummary(hook=bad.hook, state=state)
    assert is_due(later_summary, NOW) is False
    assert is_due(later_summary, "2026-06-27T02:30:00Z") is False


async def test_failed_scan_preserves_existing_state_fields(tmp_path: Path) -> None:
    # mark_scan_failed 只翻 last_scanned，不引入新字段、不覆盖既有 status/confidence。
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    bad = await store.create(_draft("Bad Due"))
    seed = await store.get_state(bad.hook.id)
    assert seed is not None
    await store.save_state(
        bad.hook.id,
        seed.model_copy(update={"status": "escalating", "confidence": 77,
                                "summary": "Prior", "last_scanned": "2026-06-27T01:00:00Z"}),
    )

    await scan_due_hooks(store, _runtime([]), now_fn=lambda: NOW)

    state = await store.get_state(bad.hook.id)
    assert state is not None
    assert (state.status, state.confidence, state.summary) == ("escalating", 77, "Prior")
    assert state.last_scanned == NOW


async def test_revive_makes_resolved_hook_due_again(tmp_path: Path) -> None:
    # 缺陷 B：resolved 钩子 cadence=0 永不 due；revive 后立即 due，状态机得以复活。
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    created = await store.create(_draft("Resolved Hook"))
    seed = await store.get_state(created.hook.id)
    assert seed is not None
    await store.save_state(created.hook.id, seed.model_copy(
        update={"status": "resolved", "last_scanned": "2026-06-27T01:00:00Z"}))

    resolved_summary = eh.HookSummary(hook=created.hook, state=await store.get_state(created.hook.id))
    assert is_due(resolved_summary, NOW) is False  # cadence 0 → 永不 due

    await store.revive(created.hook.id)
    revived_summary = eh.HookSummary(hook=created.hook, state=await store.get_state(created.hook.id))
    assert is_due(revived_summary, NOW) is True  # developing + last_scanned 清空 → 立即 due


async def test_slow_hook_times_out_and_advances_last_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # per-hook 时间预算：慢钩子超时按失败路径处理（推进 last_scanned），不拖住整个 tick。
    from backend.core.s07_task_system.event_hooks_runtime import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "HOOK_RUN_BUDGET_SECONDS", 0.05)
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    slow = await store.create(_draft("Slow Due"))
    await _set_state(store, slow, last_scanned="2026-06-27T01:00:00Z")

    async def slow_search(query: eh.TwitterQuery) -> list[SimpleNamespace]:
        await asyncio.sleep(1.0)  # 远超预算，将被超时取消
        return [_tweet()]

    runtime = _runtime([])
    runtime = runtime.model_copy(update={"twitter_search_fn": slow_search})

    outcomes = await scan_due_hooks(store, runtime, now_fn=lambda: NOW)

    assert outcomes == []  # 慢钩子无 outcome
    state = await store.get_state(slow.hook.id)
    assert state is not None and state.last_scanned == NOW  # 失败路径推进扫描时刻


async def test_hook_scheduler_starts_and_stops(tmp_path: Path) -> None:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    scheduler = HookScheduler(store, _runtime([]), tick_seconds=0.01)

    await scheduler.start()
    await asyncio.sleep(0)
    await scheduler.stop()
