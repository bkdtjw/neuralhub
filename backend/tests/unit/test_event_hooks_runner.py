from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.core.s07_task_system import event_hooks as eh
from backend.core.s07_task_system.event_hooks_runtime import HookRuntimeError

pytestmark = pytest.mark.asyncio
NOW = "2026-06-27T01:02:03Z"

@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None
@dataclass
class FakeSearch:
    account_posts: Sequence[SimpleNamespace] = ()
    topic_posts: Sequence[SimpleNamespace] = ()
    async def __call__(self, query: eh.TwitterQuery) -> Sequence[SimpleNamespace]:
        return self.account_posts if "from:" in query.query else self.topic_posts
@dataclass
class FakeExaSearch:
    hits: Sequence[SimpleNamespace] = ()
    queries: list[eh.ExaQuery] = field(default_factory=list)
    async def __call__(self, query: eh.ExaQuery) -> Sequence[SimpleNamespace]:
        self.queries.append(query)
        return self.hits
@dataclass
class FakePush:
    fail: bool = False
    calls: int = 0
    async def __call__(self, hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        assert hook.id
        assert verdict.decision == "push"
        self.calls += 1
        if self.fail:
            raise RuntimeError("delivery down")
@dataclass
class CaptureAssess:
    result: eh.Assessment
    signals: list[eh.HookSignal] | None = None
    async def __call__(self, request: eh.AssessRequest) -> eh.Assessment:
        self.signals = request.signals
        return self.result
class NoTouchStore:
    async def get_state(self, hook_id: str) -> None:
        raise AssertionError(hook_id)


def _tweet(handle: str = "newsdesk", url: str = "https://x.com/newsdesk/status/1") -> SimpleNamespace:
    return SimpleNamespace(author_handle=handle, text="Launch moved", likes=40, retweets=2, created_at="2026-06-27T00:00:00Z", url=url)
def _exa_hit(author: str = "Example News") -> SimpleNamespace:
    return SimpleNamespace(title="Launch confirmed", url="https://example.com/story", published_date="2026-06-27T00:30:00Z", author=author, highlights=["Launch window moved"], text="Launch window moved")
def _assessment(materiality: int = 92, summary: str = "Confirmed", devs: int = 3) -> eh.Assessment:
    developments = [eh.Development(text=f"Curated development {index}", ts=f"2026-06-27T00:{index:02d}:00Z", source="twitter") for index in range(devs)]
    return eh.Assessment(materiality=materiality, summary=summary, developments=developments)
def _assess(result: eh.Assessment) -> eh.AssessFn:
    async def fake(request: eh.AssessRequest) -> eh.Assessment:
        assert request.hook.id
        return result
    return fake
def _draft(
    accounts: list[str] | None = None,
    keywords: list[str] | None = None,
    materiality: int = 60,
) -> eh.HookDraft:
    return eh.HookDraft(
        name="Launch Watch",
        twitter=eh.HookTwitterConfig(accounts=accounts or [], keywords=keywords or []),
        sources=eh.HookSources(),
        cadence_minutes=45,
        materiality=materiality,
        enabled=True,
    )
async def _stored_hook(tmp_path: Path, draft: eh.HookDraft) -> tuple[eh.HookStore, eh.EventHook]:
    store = eh.HookStore(path=str(tmp_path / "event_hooks.json"))
    summary = await store.create(draft)
    return store, summary.hook
async def _execute(store: eh.HookStore, hook: eh.EventHook, search: FakeSearch, assess_fn: eh.AssessFn, push: FakePush | None = None, exa: FakeExaSearch | None = None) -> tuple[eh.RunOutcome, eh.HookState | None, FakePush]:
    sender = push or FakePush()
    outcome = await eh.run_hook(hook, store, twitter_search_fn=search, assess_fn=assess_fn, push_fn=sender, exa_search_fn=exa, now_fn=lambda: NOW)
    return outcome, await store.get_state(hook.id), sender
def _account_posts() -> tuple[SimpleNamespace, ...]:
    return (
        _tweet("alpha", "https://x.com/a/status/1"),
        _tweet("beta", "https://x.com/b/status/2"),
        _tweet("gamma", "https://x.com/c/status/3"),
    )
def _disabled_hook() -> eh.EventHook:
    return eh.EventHook(id="disabled", name="Disabled", twitter=eh.HookTwitterConfig(), sources=eh.HookSources(), cadence_minutes=45, materiality=60, enabled=False, created_at=NOW)


async def test_run_hook_twitter_disabled_skips_twitter_retrieval(tmp_path: Path) -> None:
    draft = _draft(accounts=["newsdesk"]).model_copy(
        update={"sources": eh.HookSources(twitter=False, exa_web=False, zhipu_search=False)}
    )
    store, hook = await _stored_hook(tmp_path, draft)

    class ExplodingSearch:
        async def __call__(self, query: eh.TwitterQuery) -> Sequence[SimpleNamespace]:
            raise AssertionError("twitter search should not run when source disabled")

    outcome, state, _ = await _execute(store, hook, ExplodingSearch(), _assess(_assessment()))
    assert outcome.decision == "drop"
    assert state is not None
    assert all(item.source != "twitter" for item in state.source_health)


async def test_run_hook_pushes_and_persists_high_score(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"]))
    previous = await store.get_state(hook.id)
    assert previous is not None
    await store.save_state(hook.id, previous.model_copy(update={"last_pushed_ts": "2026-06-27T00:00:00Z"}))
    outcome, state, push = await _execute(store, hook, FakeSearch(account_posts=_account_posts()), _assess(_assessment()))
    assert (outcome.decision, outcome.pushed, outcome.status) == ("push", True, "escalating")
    assert (outcome.next_cadence_minutes, outcome.new_count, push.calls) == (45, 3, 1)
    assert state is not None
    twitter = next(item for item in state.source_health if item.source == "twitter")
    assert (len(state.timeline), state.confidence, state.summary) == (3, outcome.turning_score, "Confirmed")
    assert (state.timeline[0].text, state.last_pushed_ts) == ("Curated development 2", NOW)
    assert (twitter.online, twitter.last_ok) == (True, NOW)


async def test_run_hook_soft_uses_default_none_exa_without_push(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(keywords=["launch"]))
    outcome, state, push = await _execute(store, hook, FakeSearch(topic_posts=(_tweet("topic"),)), _assess(_assessment(45, "Worth watching", 1)))
    assert (outcome.decision, outcome.pushed, outcome.next_cadence_minutes) == ("drop", False, 45)
    assert push.calls == 0
    assert state is not None
    assert (len(state.timeline), state.status) == (0, "stable")


async def test_run_hook_drop_keeps_previous_summary_and_updates_scan(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"]))
    previous = await store.get_state(hook.id)
    assert previous is not None
    await store.save_state(hook.id, previous.model_copy(update={"summary": "Previous"}))
    outcome, state, _ = await _execute(store, hook, FakeSearch(account_posts=_account_posts()), _assess(_assessment(19, "Noise veto", 0)))
    assert (outcome.decision, outcome.new_count) == ("drop", 0)
    assert state is not None
    assert (state.timeline, state.summary, state.last_scanned) == ([], "Noise veto", NOW)


async def test_run_hook_disabled_skips_without_touching_store() -> None:
    outcome = await eh.run_hook(_disabled_hook(), NoTouchStore(), twitter_search_fn=FakeSearch(), assess_fn=_assess(_assessment()), push_fn=FakePush(), now_fn=lambda: NOW)
    assert (outcome.decision, outcome.status, outcome.turning_score) == ("skipped", "stable", 0)
    assert outcome.next_cadence_minutes == 0


async def test_run_hook_empty_scan_skips_assessment_and_updates_scan(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"], keywords=["launch"]))
    previous = await store.get_state(hook.id)
    assert previous is not None
    await store.save_state(hook.id, previous.model_copy(update={"confidence": 77, "status": "escalating"}))
    async def fail_assess(request: eh.AssessRequest) -> eh.Assessment:
        raise AssertionError(f"assess_fn called with {len(request.signals)} signals")
    outcome, state, push = await _execute(store, hook, FakeSearch(), fail_assess, exa=FakeExaSearch())
    assert (outcome.decision, outcome.pushed, outcome.new_count) == ("drop", False, 0)
    assert (outcome.turning_score, outcome.status, push.calls) == (77, "escalating", 0)
    assert state is not None
    twitter = next(item for item in state.source_health if item.source == "twitter")
    assert (state.last_scanned, twitter.online, twitter.last_ok) == (NOW, True, NOW)


async def test_run_hook_push_failure_does_not_rollback_or_raise(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"]))
    outcome, state, _ = await _execute(store, hook, FakeSearch(account_posts=_account_posts()), _assess(_assessment()), FakePush(fail=True))
    assert (outcome.decision, outcome.pushed) == ("push", False)
    assert state is not None
    assert (state.summary, len(state.timeline), state.last_pushed_ts) == ("Confirmed", 3, "")


async def test_run_hook_merges_exa_signals_before_assessment(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"], keywords=["launch"]))
    capture = CaptureAssess(_assessment(devs=2))
    exa = FakeExaSearch(hits=(_exa_hit(),))
    outcome, _, _ = await _execute(store, hook, FakeSearch(account_posts=(_tweet("alpha"),)), capture, exa=exa)
    assert capture.signals is not None
    assert [signal.source for signal in capture.signals] == ["twitter", "exa"]
    assert (outcome.decision, outcome.new_count, exa.queries[0].query) == ("push", 2, "launch")


async def test_run_hook_no_developments_leaves_timeline_without_push(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(keywords=["launch"]))
    outcome, state, push = await _execute(store, hook, FakeSearch(topic_posts=(_tweet("topic"),)), _assess(eh.Assessment(materiality=90, summary="Current situation")), exa=FakeExaSearch(hits=(_exa_hit(),)))
    assert (outcome.decision, outcome.pushed, push.calls, outcome.new_count) == ("drop", False, 0, 0)
    assert state is not None
    assert (state.summary, state.timeline) == ("Current situation", [])


async def test_run_hook_push_cooldown_persists_entries_without_delivery(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"]))
    previous = await store.get_state(hook.id)
    assert previous is not None
    await store.save_state(hook.id, previous.model_copy(update={"last_pushed_ts": NOW}))
    outcome, state, push = await _execute(store, hook, FakeSearch(account_posts=_account_posts()), _assess(_assessment(devs=1)))
    assert (outcome.decision, outcome.pushed, push.calls, outcome.new_count) == ("push", False, 0, 1)
    assert state is not None
    assert (len(state.timeline), state.last_pushed_ts) == (1, NOW)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("escalating", 45), ("developing", 45), ("stable", 45), ("resolved", 0)],
)
async def test_adaptive_cadence_branches(status: eh.HookStatus, expected: int) -> None:
    assert eh.adaptive_cadence(status, 45) == expected


async def test_run_hook_push_delivery_failure_keeps_last_pushed_unwritten(tmp_path: Path) -> None:
    # 投递失败（push.py 把 code!=0 变成 HookRuntimeError）经 runner 后：pushed=False 且不写 last_pushed_ts，
    # 否则冷却会误吞后续告警。
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"]))

    async def failing_push(_hook: eh.EventHook, _verdict: eh.HookVerdict) -> None:
        raise HookRuntimeError("HOOK_RUNTIME_PUSH_DELIVERY_FAILED: code=19001 msg=bot removed")

    outcome = await eh.run_hook(
        hook, store, twitter_search_fn=FakeSearch(account_posts=_account_posts()),
        assess_fn=_assess(_assessment()), push_fn=failing_push, now_fn=lambda: NOW,
    )
    state = await store.get_state(hook.id)
    assert (outcome.decision, outcome.pushed) == ("push", False)
    assert state is not None
    assert (len(state.timeline), state.last_pushed_ts) == (3, "")


@dataclass
class GatedPush:
    started: asyncio.Event
    release: asyncio.Event
    calls: int = 0

    async def __call__(self, hook: eh.EventHook, verdict: eh.HookVerdict) -> None:
        self.calls += 1
        self.started.set()
        await self.release.wait()


class OrderTrackingStore:
    # 包装真实 store，记录 get_state / save_state 调用顺序，用于断言两次扫描被串行化。
    def __init__(self, inner: eh.HookStore, events: list[str]) -> None:
        self._inner = inner
        self._events = events

    async def get_state(self, hook_id: str):  # type: ignore[no-untyped-def]
        self._events.append("get_state")
        return await self._inner.get_state(hook_id)

    async def save_state(self, hook_id: str, state):  # type: ignore[no-untyped-def]
        self._events.append("save_state")
        return await self._inner.save_state(hook_id, state)

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._inner, name)


@dataclass
class SwitchingAssess:
    # 每次调用返回不同的 development，使两次扫描都各自会判为 push——
    # 从而把第二次的 pushed=False 归因唯一锁定在冷却（而非去重降级为 drop）上。
    results: list[eh.Assessment]
    index: int = 0

    async def __call__(self, request: eh.AssessRequest) -> eh.Assessment:
        assert request.hook.id
        result = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return result


async def test_run_hook_concurrent_same_hook_serialized_no_double_push(tmp_path: Path) -> None:
    store, hook = await _stored_hook(tmp_path, _draft(accounts=["newsdesk"]))
    events: list[str] = []
    tracked = OrderTrackingStore(store, events)
    push = GatedPush(started=asyncio.Event(), release=asyncio.Event())
    search = FakeSearch(account_posts=_account_posts())
    # 两轮各带一条独立高重要度进展：均独立判 push，第二次唯一的拦截理由只能是冷却。
    assess = SwitchingAssess(results=[
        _assessment(summary="First round", devs=0).model_copy(update={
            "developments": [eh.Development(text="Alpha breaking", ts="2026-06-27T00:10:00Z", source="twitter")]}),
        _assessment(summary="Second round", devs=0).model_copy(update={
            "developments": [eh.Development(text="Beta breaking", ts="2026-06-27T00:20:00Z", source="twitter")]}),
    ])

    def run() -> "asyncio.Future[eh.RunOutcome]":
        return asyncio.ensure_future(
            eh.run_hook(hook, tracked, twitter_search_fn=search,
                        assess_fn=assess, push_fn=push, now_fn=lambda: NOW)
        )

    first = run()
    await push.started.wait()  # 第一次已进入锁内并挂在 push 上
    second = run()
    await asyncio.sleep(0.05)  # 给第二次机会去抢跑（应被锁挡住）
    # 第二次此时不得读取 state —— 只应有第一次那一次 get_state。
    assert events.count("get_state") == 1
    push.release.set()
    out1, out2 = await asyncio.gather(first, second)

    # 严格串行：第一次整段(get_state...save_state)结束后第二次才 get_state。
    assert events == ["get_state", "save_state", "get_state", "save_state"]
    # 两次都判 push，但只投递一次——第二次读到刷新后的 last_pushed_ts 被冷却拦截。
    assert (out1.decision, out2.decision) == ("push", "push")
    assert push.calls == 1
    assert (out1.pushed, out2.pushed) == (True, False)
    # timeline 无丢失：两条独立进展都在，第二次没有用旧快照抹掉第一次。
    final = await store.get_state(hook.id)
    assert final is not None
    texts = {entry.text for entry in final.timeline}
    assert texts == {"Alpha breaking", "Beta breaking"} and final.last_pushed_ts == NOW
