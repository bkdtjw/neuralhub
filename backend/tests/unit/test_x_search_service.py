from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from backend.api import x_search_service
from backend.api.x_search_service import XSearchQuery, run_x_search
from backend.common.x_budget import XBudgetError
from backend.config.settings import settings
from backend.core.s02_tools.builtin.x_client import XClientConfig, XPost, XRateLimitError

pytestmark = pytest.mark.asyncio

_CFG = XClientConfig(password="secret")


@pytest.fixture(autouse=True)
def bind_test_database() -> Generator[None, None, None]:
    # 覆盖 conftest 真库绑定：本模块纯内存（fakeredis + mock 搜索），跳过 PostgresContainer。
    yield


def _post(text: str = "hi") -> XPost:
    return XPost(
        author_name="Alice", author_handle="alice", text=text,
        likes=1, retweets=0, replies=0, views=10,
        created_at="2026-01-01", url="https://x.com/alice/1",
    )


def _q(query: str = "claude", days: int = 7, limit: int = 5, search_type: str = "Latest") -> XSearchQuery:
    return XSearchQuery(query=query, days=days, limit=limit, search_type=search_type)


def _budget(monkeypatch: pytest.MonkeyPatch, *, interval: float, budget: int, ttl: int) -> None:
    monkeypatch.setattr(settings, "x_call_min_interval_seconds", interval)
    monkeypatch.setattr(settings, "x_daily_call_budget", budget)
    monkeypatch.setattr(settings, "x_search_cache_ttl_seconds", ttl)


def _fake_search(calls: list[str], posts: list[XPost]) -> Any:
    async def _search(query: str, config: XClientConfig, options: object) -> list[XPost]:
        calls.append(query)
        return posts
    return _search


async def test_cache_hit_skips_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _budget(monkeypatch, interval=0.0, budget=100, ttl=300)
    calls: list[str] = []
    monkeypatch.setattr(x_search_service, "search_x_posts", _fake_search(calls, [_post("r1")]))

    first = await run_x_search(_CFG, _q())
    assert first.cached is False and len(first.posts) == 1
    second = await run_x_search(_CFG, _q())
    assert second.cached is True and len(second.posts) == 1
    assert calls == ["claude"]  # 第二次命中缓存，未再打 X


async def test_daily_budget_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _budget(monkeypatch, interval=0.0, budget=1, ttl=0)  # 关最小间隔+缓存，专测日额度
    monkeypatch.setattr(x_search_service, "search_x_posts", _fake_search([], [_post()]))

    await run_x_search(_CFG, _q(query="k1"))  # 用掉当天唯一额度
    with pytest.raises(XBudgetError):
        await run_x_search(_CFG, _q(query="k2"))  # 超额被拒


async def test_min_interval_gate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _budget(monkeypatch, interval=60.0, budget=100, ttl=0)  # 大间隔+关缓存，专测限速
    monkeypatch.setattr(x_search_service, "search_x_posts", _fake_search([], [_post()]))

    await run_x_search(_CFG, _q(query="a"))  # 第一次设闸
    with pytest.raises(XBudgetError):
        await run_x_search(_CFG, _q(query="b"))  # 60s 内第二次被限速


async def test_rate_limit_passthrough_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _budget(monkeypatch, interval=0.0, budget=100, ttl=300)
    calls: list[str] = []

    async def _search(query: str, config: XClientConfig, options: object) -> list[XPost]:
        calls.append(query)
        raise XRateLimitError([_post("partial")], 30)

    monkeypatch.setattr(x_search_service, "search_x_posts", _search)

    result = await run_x_search(_CFG, _q())
    assert result.rate_limited is True and result.retry_after == 30
    assert len(result.posts) == 1  # 半份结果如实透传
    await run_x_search(_CFG, _q())
    assert calls == ["claude", "claude"]  # 限流结果不缓存，再搜仍会调用


async def test_degrades_open_when_redis_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _budget(monkeypatch, interval=60.0, budget=1, ttl=300)  # 即便额度=1、间隔=60
    monkeypatch.setattr("backend.common.x_budget.get_redis", lambda: None)
    monkeypatch.setattr("backend.api.x_search_service.get_redis", lambda: None)
    calls: list[str] = []
    monkeypatch.setattr(x_search_service, "search_x_posts", _fake_search(calls, [_post()]))

    await run_x_search(_CFG, _q(query="a"))
    await run_x_search(_CFG, _q(query="a"))  # Redis 挂：闸门放行、缓存跳过，不抛不拦
    assert len(calls) == 2
