from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any

import pytest

from backend.api.x_monitor_runner import crossing_reason, process_monitor, run_monitor_cycle
from backend.api.x_search_service import XSearchResult
from backend.common.x_budget import XBudgetError
from backend.core.s02_tools.builtin.x_client import XPost
from backend.storage.x_monitor_models import XMonitor

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 7, 10, 12, 0, 0)


@pytest.fixture(autouse=True)
def bind_test_database() -> Generator[None, None, None]:
    # 纯逻辑测试（假 store），跳过 PostgresContainer。
    yield


def _monitor(*, likes: int = 100, views: int = 0, monitor_id: str = "m1") -> XMonitor:
    return XMonitor(
        id=monitor_id, query="claude", interval_minutes=15, days_window=1,
        search_type="Latest", threshold_likes=likes, threshold_views=views,
        enabled=True, created_at=_NOW, last_run_at=None, last_status="",
    )


def _post(*, likes: int = 0, views: int = 0, url: str = "https://x.com/a/1") -> XPost:
    return XPost(
        author_name="A", author_handle="a", text="hello world",
        likes=likes, retweets=0, replies=0, views=views,
        created_at="2026-07-10", url=url,
    )


class FakeStore:
    def __init__(self, monitors: list[XMonitor] | None = None, *, dup_urls: set[str] | None = None) -> None:
        self.monitors = monitors or []
        self.dup_urls = dup_urls or set()
        self.hits: list[dict[str, Any]] = []
        self.notified: list[tuple[str, bool]] = []
        self.runs: list[tuple[str, str]] = []
        self.insert_error: Exception | None = None

    async def list_due(self, now: datetime) -> list[XMonitor]:
        return list(self.monitors)

    async def insert_hit(self, fields: dict[str, Any]) -> str | None:
        if self.insert_error is not None:
            raise self.insert_error
        if fields["tweet_url"] in self.dup_urls:
            return None
        self.hits.append(fields)
        return f"hit-{len(self.hits)}"

    async def set_hit_notified(self, hit_id: str, notified: bool) -> None:
        self.notified.append((hit_id, notified))

    async def mark_run(self, monitor_id: str, status: str, now: datetime) -> None:
        self.runs.append((monitor_id, status))


def _search_returning(posts: list[XPost], *, rate_limited: bool = False):
    async def search(monitor: XMonitor) -> XSearchResult:
        return XSearchResult(posts=posts, rate_limited=rate_limited)
    return search


def _notify_recording(calls: list[str], *, ok: bool = True):
    async def notify(monitor: XMonitor, post: XPost, reason: str) -> bool:
        calls.append(post.url)
        return ok
    return notify


def test_crossing_reason_thresholds() -> None:
    assert crossing_reason(_monitor(likes=100), _post(likes=150)) == "likes>=100"
    assert crossing_reason(_monitor(likes=100), _post(likes=99)) == ""
    assert crossing_reason(_monitor(likes=0, views=1000), _post(views=5000)) == "views>=1000"
    # 阈值为 0 的维度不参与判定（0 赞不会因 likes>=0 而误报）
    assert crossing_reason(_monitor(likes=100, views=0), _post(likes=0, views=999999)) == ""


async def test_process_monitor_hits_and_notifies() -> None:
    store = FakeStore()
    calls: list[str] = []
    monitor = _monitor(likes=100)
    posts = [_post(likes=150, url="https://x.com/a/1"), _post(likes=5, url="https://x.com/a/2")]

    status = await process_monitor(store, monitor, _search_returning(posts), _notify_recording(calls), _NOW)

    assert status == "ok"
    assert [h["tweet_url"] for h in store.hits] == ["https://x.com/a/1"]  # 只有过阈值的入库
    assert calls == ["https://x.com/a/1"]  # 且告警一次
    assert store.notified == [("hit-1", True)]


async def test_process_monitor_dedupes_known_tweet() -> None:
    store = FakeStore(dup_urls={"https://x.com/a/1"})
    calls: list[str] = []

    status = await process_monitor(
        store, _monitor(likes=100), _search_returning([_post(likes=150)]), _notify_recording(calls), _NOW
    )

    assert status == "ok"
    assert store.hits == [] and calls == []  # 已记过的推文：不重复入库、不重复告警


async def test_process_monitor_records_notify_failure() -> None:
    store = FakeStore()
    calls: list[str] = []

    await process_monitor(
        store, _monitor(likes=100), _search_returning([_post(likes=150)]),
        _notify_recording(calls, ok=False), _NOW,
    )

    assert store.notified == [("hit-1", False)]  # 发送失败如实落 notified=False，不抛不炸


async def test_process_monitor_maps_budget_and_rate_limit_status() -> None:
    async def search_budget(monitor: XMonitor) -> XSearchResult:
        raise XBudgetError("额度用尽", 3600)

    assert await process_monitor(FakeStore(), _monitor(), search_budget, _notify_recording([]), _NOW) == "budget"
    assert (
        await process_monitor(
            FakeStore(), _monitor(), _search_returning([], rate_limited=True), _notify_recording([]), _NOW
        )
        == "rate_limited"
    )


async def test_cycle_isolates_per_monitor_failure() -> None:
    good, bad = _monitor(monitor_id="good"), _monitor(monitor_id="bad")
    store = FakeStore(monitors=[bad, good])
    calls: list[str] = []

    async def search(monitor: XMonitor) -> XSearchResult:
        if monitor.id == "bad":
            raise RuntimeError("boom")
        return XSearchResult(posts=[_post(likes=150)])

    await run_monitor_cycle(store, search, _notify_recording(calls), _NOW)

    # bad 标 error，good 照常跑完并告警——单条失败不打断其余监控
    assert ("bad", "error") in store.runs and ("good", "ok") in store.runs
    assert calls == ["https://x.com/a/1"]
