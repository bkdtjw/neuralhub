from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from backend.core.s07_task_system import event_hooks as eh
from backend.core.s07_task_system.event_hooks_runtime import HookRuntime, HookRuntimeError
from backend.core.s07_task_system.event_hooks_runtime.sweep import sweep_pending_pushes

pytestmark = pytest.mark.asyncio
NOW = "2026-06-27T02:00:00Z"
COOLED = "2026-06-27T00:00:00Z"  # 距 NOW 120 分钟，冷却(30min)已过
HOT = "2026-06-27T01:50:00Z"  # 距 NOW 10 分钟，仍在冷却窗内


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


@dataclass
class RecordingPush:
    fail: bool = False
    calls: list[tuple[str, eh.HookVerdict]] = field(default_factory=list)

    async def __call__(self, hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        self.calls.append((hook.name, verdict))
        if self.fail:
            raise HookRuntimeError("HOOK_RUNTIME_PUSH_DELIVERY_FAILED: code=19001")


def _runtime(push: RecordingPush) -> HookRuntime:
    async def unused(*_args: object, **_kwargs: object) -> list[object]:
        return []

    async def assess(_request: eh.AssessRequest) -> eh.Assessment:
        return eh.Assessment(materiality=0)

    return HookRuntime(
        twitter_search_fn=unused, assess_fn=assess, push_fn=push, exa_search_fn=unused
    )


def _draft(name: str = "Cooled Hook") -> eh.HookDraft:
    return eh.HookDraft(
        name=name,
        twitter=eh.HookTwitterConfig(accounts=["newsdesk"]),
        sources=eh.HookSources(),
        cadence_minutes=45,
        materiality=60,
        enabled=True,
    )


async def _pending_hook(
    tmp_path: Path, *, last_pushed: str, pending: bool = True, confidence: int = 88,
) -> tuple[eh.HookStore, eh.EventHook]:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    created = await store.create(_draft())
    await store.append_timeline(created.hook.id, [
        eh.TimelineEntry(ts="2026-06-27T01:00:00Z", text="Breaking one", source="twitter"),
        eh.TimelineEntry(ts="2026-06-27T01:30:00Z", text="Breaking two", source="twitter"),
    ])
    state = await store.get_state(created.hook.id)
    assert state is not None
    await store.save_state(created.hook.id, state.model_copy(update={
        "pending_push": pending, "last_pushed_ts": last_pushed,
        "confidence": confidence, "summary": "局势摘要", "status": "escalating"}))
    return store, created.hook


async def test_sweep_delivers_digest_and_clears_pending(tmp_path: Path) -> None:
    # 缺陷 A：pending 且冷却已过 → 补推成功后清 pending_push 并写 last_pushed_ts。
    store, hook = await _pending_hook(tmp_path, last_pushed=COOLED)
    push = RecordingPush()

    delivered = await sweep_pending_pushes(store, _runtime(push), now_fn=lambda: NOW)

    assert delivered == 1
    assert len(push.calls) == 1
    name, verdict = push.calls[0]
    # 摘要卡：标题走钩子名，正文=state.summary + 最近 3 条 timeline，置信度=state.confidence。
    assert name == hook.name
    assert (verdict.decision, verdict.summary, verdict.turning_score) == ("push", "局势摘要", 88)
    assert [entry.text for entry in verdict.new_entries] == ["Breaking two", "Breaking one"]
    state = await store.get_state(hook.id)
    assert state is not None
    assert (state.pending_push, state.last_pushed_ts) == (False, NOW)


async def test_sweep_keeps_pending_when_delivery_fails(tmp_path: Path) -> None:
    # 缺陷 A：补推失败保持 pending（且不写 last_pushed_ts），下一 tick 再试；best-effort 不抛。
    store, hook = await _pending_hook(tmp_path, last_pushed=COOLED)
    push = RecordingPush(fail=True)

    delivered = await sweep_pending_pushes(store, _runtime(push), now_fn=lambda: NOW)

    assert delivered == 0
    assert len(push.calls) == 1  # 确实尝试过
    state = await store.get_state(hook.id)
    assert state is not None
    assert (state.pending_push, state.last_pushed_ts) == (True, COOLED)


async def test_sweep_skips_hook_still_in_cooldown(tmp_path: Path) -> None:
    # 缺陷 A：pending 但冷却未过 → 不补推，等冷却窗过后再由后续 tick 处理。
    store, hook = await _pending_hook(tmp_path, last_pushed=HOT)
    push = RecordingPush()

    delivered = await sweep_pending_pushes(store, _runtime(push), now_fn=lambda: NOW)

    assert delivered == 0 and push.calls == []
    state = await store.get_state(hook.id)
    assert state is not None
    assert state.pending_push is True  # 保留待后续补推


async def test_sweep_ignores_non_pending_hooks(tmp_path: Path) -> None:
    # pending_push=False 的钩子不补推，即便冷却已过。
    store, _ = await _pending_hook(tmp_path, last_pushed=COOLED, pending=False)
    push = RecordingPush()

    delivered = await sweep_pending_pushes(store, _runtime(push), now_fn=lambda: NOW)

    assert delivered == 0 and push.calls == []
