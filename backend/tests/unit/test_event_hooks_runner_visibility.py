from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.s07_task_system import event_hooks as eh

pytestmark = pytest.mark.asyncio
NOW = "2026-06-27T01:02:03Z"


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


@dataclass
class FakeSearch:
    account_posts: Sequence[SimpleNamespace] = ()

    async def __call__(self, query: eh.TwitterQuery) -> Sequence[SimpleNamespace]:
        _ = query
        return self.account_posts


@dataclass
class FakePush:
    calls: int = 0

    async def __call__(self, hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        assert hook.id and verdict.decision == "push"
        self.calls += 1


@dataclass
class CaptureAssess:
    result: eh.Assessment
    signals: list[eh.HookSignal] | None = None
    recent: list[str] | None = None

    async def __call__(self, request: eh.AssessRequest) -> eh.Assessment:
        self.signals = request.signals
        self.recent = request.recent_developments
        return self.result


def _tweet(handle: str = "newsdesk", url: str = "https://x.com/newsdesk/status/1") -> SimpleNamespace:
    return SimpleNamespace(
        author_handle=handle,
        text="Launch moved",
        likes=40,
        retweets=2,
        created_at="2026-06-27T00:00:00Z",
        url=url,
    )


def _hook_draft(materiality: int = 60) -> eh.HookDraft:
    return eh.HookDraft(
        name="Launch Watch",
        twitter=eh.HookTwitterConfig(accounts=["newsdesk"], keywords=[]),
        sources=eh.HookSources(exa_web=False, zhipu_search=False),
        cadence_minutes=45,
        materiality=materiality,
        enabled=True,
    )


def _assessment(materiality: int, summary: str) -> eh.Assessment:
    return eh.Assessment(
        materiality=materiality,
        summary=summary,
        developments=[eh.Development(text="Curated development", source="twitter")],
    )


async def _stored_hook(tmp_path: Path, materiality: int = 60) -> tuple[eh.HookStore, eh.EventHook]:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    summary = await store.create(_hook_draft(materiality))
    return store, summary.hook


async def _run(
    store: eh.HookStore,
    hook: eh.EventHook,
    assess_fn: eh.AssessFn,
) -> tuple[eh.RunOutcome, eh.HookState | None, FakePush]:
    push = FakePush()
    posts = (
        _tweet("alpha", "https://x.com/a/status/1"),
        _tweet("beta", "https://x.com/b/status/2"),
        _tweet("gamma", "https://x.com/c/status/3"),
    )
    outcome = await eh.run_hook(
        hook,
        store,
        twitter_search_fn=FakeSearch(account_posts=posts),
        assess_fn=assess_fn,
        push_fn=push,
        now_fn=lambda: NOW,
    )
    return outcome, await store.get_state(hook.id), push


async def test_materiality_below_user_threshold_is_hidden(tmp_path: Path) -> None:
    # 默认门槛 60：materiality 55 未越过 → drop 且不记 timeline。
    store, hook = await _stored_hook(tmp_path)
    outcome, state, push = await _run(store, hook, lambda _: _async_assessment(55, "Not enough"))

    assert (outcome.decision, outcome.pushed, outcome.new_count, push.calls) == ("drop", False, 0, 0)
    assert state is not None
    assert (state.timeline, state.status, state.summary) == ([], "stable", "Not enough")
    assert state.confidence == outcome.turning_score


async def test_high_user_threshold_blocks_material_below_gate(tmp_path: Path) -> None:
    # 用户把门槛设到 90：materiality 86 不越过 → 不推、不记 timeline。
    # 固化前用硬编码 80 时此例会误推——现在门槛跟随 hook.materiality。
    store, hook = await _stored_hook(tmp_path, materiality=90)
    outcome, state, push = await _run(store, hook, lambda _: _async_assessment(86, "Major turn"))

    assert (outcome.decision, outcome.pushed, outcome.new_count, push.calls) == ("drop", False, 0, 0)
    assert state is not None
    assert (state.status, state.timeline) == ("stable", [])


async def test_low_user_threshold_pushes_and_records_timeline(tmp_path: Path) -> None:
    # 用户把门槛降到 40：materiality 45 越过 → 推送且记 timeline。
    # 固化前用硬编码 80 时此例会被拦下——现在门槛跟随 hook.materiality。
    store, hook = await _stored_hook(tmp_path, materiality=40)
    outcome, state, push = await _run(store, hook, lambda _: _async_assessment(45, "Modest turn"))

    assert (outcome.decision, outcome.pushed, outcome.new_count, push.calls) == ("push", True, 1, 1)
    assert state is not None
    assert (state.status, state.summary, len(state.timeline)) == ("escalating", "Modest turn", 1)


async def test_assessor_receives_current_scan_and_recorded_timeline(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path)
    await store.append_timeline(hook.id, [eh.TimelineEntry(ts=NOW, text="Already shown", source="twitter")])
    capture = CaptureAssess(eh.Assessment(materiality=19, summary="No new fact"))

    outcome, _, push = await _run(store, hook, capture)

    assert capture.signals is not None
    assert (capture.signals[0].text, push.calls, outcome.decision) == ("Launch moved", 0, "drop")
    assert capture.recent == ["Already shown"]


async def _async_assessment(materiality: int, summary: str) -> eh.Assessment:
    return _assessment(materiality, summary)
