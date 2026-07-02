from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.s07_task_system import event_hooks as eh

NOW = "2026-06-29T13:30:00Z"


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


@dataclass
class FakePush:
    calls: int = 0

    async def __call__(self, hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        self.calls += 1


def _draft() -> eh.HookDraft:
    return eh.HookDraft(
        name="Fable 5 Watch",
        twitter=eh.HookTwitterConfig(accounts=["axios"], keywords=["Fable 5"]),
        sources=eh.HookSources(exa_web=False, zhipu_search=False),
        cadence_minutes=40,
        materiality=60,
        enabled=True,
    )


def _entry(text: str, ts: str = "2026-06-27T12:57:03Z") -> eh.TimelineEntry:
    return eh.TimelineEntry(ts=ts, text=text, source="twitter")


def _signal(url: str) -> eh.HookSignal:
    return eh.HookSignal(
        source="twitter",
        lane="account",
        text="Axios says Fable 5 will return soon",
        url=url,
        author="axios",
        ts="2026-06-27T12:57:03Z",
        engagement=50,
    )


def test_dedupe_signals_collapses_same_tweet_url() -> None:
    signals = [
        _signal("https://x.com/axios/status/777"),
        _signal("https://twitter.com/other/status/777?ref=feed"),
    ]

    assert len(eh.dedupe_signals(signals)) == 1


def test_visible_verdict_drops_duplicate_push_entry() -> None:
    state = eh.HookState(
        hook_id="hook-1",
        timeline=[_entry("Axios exclusive says Fable 5 will return soon.")],
    )
    verdict = eh.HookVerdict(
        turning_score=91,
        numeric=90,
        materiality=92,
        status="escalating",
        decision="push",
        summary="Same story",
        new_entries=[_entry("Axios says Fable 5 will return soon")],
    )

    visible = eh.visible_verdict(verdict, state)

    assert (visible.decision, visible.status, visible.new_entries) == ("drop", "stable", [])


def test_visible_verdict_high_threshold_drops_below_user_gate() -> None:
    # 用户门槛 90：materiality 86 未越过 → drop 且不记 timeline（新条目清空）。
    verdict = eh.HookVerdict(
        turning_score=82,
        numeric=100,
        materiality=86,
        status="escalating",
        decision="push",
        summary="Material but below user gate",
        new_entries=[_entry("Fresh but not material enough", "2026-06-29T13:00:00Z")],
    )

    visible = eh.visible_verdict(verdict, None, 90)

    assert (visible.decision, visible.status, visible.new_entries) == ("drop", "stable", [])


def test_visible_verdict_low_threshold_pushes_and_keeps_entries() -> None:
    # 用户门槛 40：materiality 45 越过 → push 且保留新条目（记 timeline）。
    verdict = eh.HookVerdict(
        turning_score=45,
        numeric=10,
        materiality=45,
        status="developing",
        decision="soft",
        summary="LLM sees a modest turn",
        new_entries=[_entry("Official access restored", "2026-06-29T14:00:00Z")],
    )

    visible = eh.visible_verdict(verdict, None, 40)

    assert (visible.decision, visible.status, len(visible.new_entries)) == ("push", "escalating", 1)


def test_visible_verdict_uses_llm_materiality_not_turning_decision() -> None:
    # 门槛参数由 hook.materiality 传入；此处默认门槛(60)下 materiality 86 越过 → push。
    verdict = eh.HookVerdict(
        turning_score=45,
        numeric=10,
        materiality=86,
        status="developing",
        decision="soft",
        summary="LLM sees a major turn",
        new_entries=[_entry("Official access restored", "2026-06-29T14:00:00Z")],
    )

    visible = eh.visible_verdict(verdict, None)

    assert (visible.decision, visible.status, len(visible.new_entries)) == ("push", "escalating", 1)


@pytest.mark.asyncio
async def test_duplicate_assessment_entry_is_not_pushed_or_appended(tmp_path: Path) -> None:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    summary = await store.create(_draft())
    hook = summary.hook
    await store.append_timeline(
        hook.id,
        [_entry("Axios exclusive says Fable 5 will return soon.")],
    )

    async def search(_: eh.TwitterQuery) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                author_handle="fresh",
                text="Different raw chatter before assessment",
                likes=80,
                retweets=5,
                created_at="2026-06-29T13:00:00Z",
                url="https://x.com/fresh/status/999",
            )
        ]

    async def assess(_: eh.AssessRequest) -> eh.Assessment:
        return eh.Assessment(
            materiality=95,
            summary="Same story, no new fact",
            developments=[eh.Development(text="Axios says Fable 5 will return soon", source="twitter")],
        )

    push = FakePush()
    outcome = await eh.run_hook(
        hook,
        store,
        twitter_search_fn=search,
        assess_fn=assess,
        push_fn=push,
        now_fn=lambda: NOW,
    )
    state = await store.get_state(hook.id)

    assert (outcome.decision, outcome.pushed, outcome.new_count, push.calls) == ("drop", False, 0, 0)
    assert state is not None
    assert len(state.timeline) == 1
    assert (state.summary, state.confidence, state.last_scanned) == ("Same story, no new fact", 80, NOW)


@pytest.mark.asyncio
async def test_store_reads_hide_legacy_duplicate_timeline(tmp_path: Path) -> None:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    summary = await store.create(_draft())
    duplicate = [
        _entry("Axios exclusive says Fable 5 will return soon."),
        _entry("Axios says Fable 5 will return soon"),
    ]
    await store.save_state(
        summary.hook.id,
        eh.HookState(hook_id=summary.hook.id, timeline=duplicate, unseen_count=2),
    )

    state = await store.get_state(summary.hook.id)
    shown = await store.get_summary(summary.hook.id)

    assert state is not None
    assert (len(state.timeline), state.unseen_count) == (1, 1)
    assert shown is not None and shown.state is not None
    assert len(shown.state.timeline) == 1
