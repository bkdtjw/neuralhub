from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.core.s02_tools import ToolRegistry
from backend.core.s02_tools.builtin import register_builtin_tools
from backend.tests.unit.x_test_support import (
    FakeClient,
    FakeResult,
    FakeTooManyRequests,
    FakeTweet,
    FakeUser,
    load_modules,
)


def _make_config(x_client: object):
    return x_client.XClientConfig(
        username="tester",
        email="tester@example.com",
        password="secret",
        proxy_url="http://127.0.0.1:7892",
        cookies_file="twitter_cookies.json",
    )


@pytest.mark.asyncio
async def test_x_search_returns_formatted_results(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, x_search = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult(
        [
            FakeTweet(
                id="111",
                text="Claude Code skill system is well designed",
                user=FakeUser("Peter", "steipete"),
                favorite_count=234,
                retweet_count=45,
                reply_count=12,
                view_count=8901,
            ),
            FakeTweet(
                id="222",
                text="Refactored backend with Claude Code in 4 hours",
                user=FakeUser("AI Dev", "maboroshi_ai"),
                favorite_count=189,
                retweet_count=32,
                reply_count=8,
                view_count=5432,
            ),
        ]
    )
    _, execute = x_search.create_x_search_tool(_make_config(x_client))
    result = await execute({"query": "Claude Code", "max_results": 2})
    assert result.is_error is False
    assert "@steipete" in result.output and "likes: 234" in result.output
    assert "https://x.com/maboroshi_ai/status/222" in result.output


@pytest.mark.asyncio
async def test_x_search_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, x_search = load_modules(monkeypatch)
    _, execute = x_search.create_x_search_tool(_make_config(x_client))
    result = await execute({"query": "   "})
    assert result.is_error is True and "搜索关键词不能为空" in result.output


@pytest.mark.asyncio
async def test_x_search_includes_date_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult([])
    monkeypatch.setattr(x_client, "_utcnow", lambda: datetime(2026, 3, 30, 0, 0, tzinfo=UTC))
    posts = await x_client.search_x_posts("Claude Code", _make_config(x_client))
    assert posts == []
    assert FakeClient.search_calls[0][0] == "Claude Code since:2026-02-28"


@pytest.mark.asyncio
async def test_x_search_handles_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, x_search = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult(
        [FakeTweet(id="111", text="Partial result", user=FakeUser("Peter", "steipete"))],
        next_exception=FakeTooManyRequests(10_000_100),
    )
    monkeypatch.setattr(x_client.time, "time", lambda: 10_000_000)
    _, execute = x_search.create_x_search_tool(_make_config(x_client))
    result = await execute({"query": "Claude Code", "max_results": 25})
    assert result.is_error is False
    assert "rate-limited" in result.output and "Partial result" in result.output


@pytest.mark.asyncio
async def test_x_search_handles_login_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, x_search = load_modules(monkeypatch)
    FakeClient.login_exception = RuntimeError("bad login")
    _, execute = x_search.create_x_search_tool(_make_config(x_client))
    result = await execute({"query": "Claude Code"})
    assert result.is_error is True
    assert "X/Twitter 登录失败" in result.output


@pytest.mark.asyncio
async def test_x_search_concurrent_first_build_logs_in_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # 并发首建：模块级锁 + 锁内二次判定，保证只 login 一次、只建一个客户端。
    x_client, _ = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult([])
    config = _make_config(x_client)

    await asyncio.gather(
        x_client.search_x_posts("Claude Code", config),
        x_client.search_x_posts("Claude Code", config),
        x_client.search_x_posts("Claude Code", config),
    )

    assert len(FakeClient.login_calls) == 1
    assert len(FakeClient.init_args) == 1


@pytest.mark.asyncio
async def test_x_search_passes_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult([])
    await x_client.search_x_posts("Claude Code", _make_config(x_client))
    assert FakeClient.init_args[0] == ("en-US", "http://127.0.0.1:7892")


@pytest.mark.asyncio
async def test_x_search_handles_zero_results(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, x_search = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult([])
    _, execute = x_search.create_x_search_tool(_make_config(x_client))
    result = await execute({"query": "nonexistent topic"})
    assert result.is_error is False
    assert "No matching tweets found" in result.output


@pytest.mark.asyncio
async def test_x_search_limits_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    FakeClient.search_response = FakeResult([FakeTweet(id=str(index)) for index in range(5)])
    posts = await x_client.search_x_posts(
        "Claude Code",
        _make_config(x_client),
        x_client.XSearchOptions(max_results=2, days=30, search_type="Latest"),
    )
    assert len(posts) == 2


def test_x_search_tool_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, x_search = load_modules(monkeypatch)
    tool, _ = x_search.create_x_search_tool(_make_config(x_client))
    assert tool.name == "x_search" and tool.category == "search"


def test_tweet_to_post_handles_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    post = x_client._tweet_to_post(
        FakeTweet(
            id="111",
            text=None,
            user=None,
            favorite_count=None,
            retweet_count=None,
            reply_count=None,
            view_count=None,
            created_at=None,
        )
    )
    assert post.author_name == "" and post.author_handle == ""
    assert post.likes == 0 and post.views == 0 and post.url == ""


def test_tweet_url_format(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    post = x_client._tweet_to_post(FakeTweet(id="999", user=FakeUser("Peter", "steipete")))
    assert post.url == "https://x.com/steipete/status/999"


def test_resolve_auth_inputs_supports_email_only(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    auth_info_1, auth_info_2 = x_client._resolve_auth_inputs(
        x_client.XClientConfig(email="tester@example.com", password="secret")
    )
    assert auth_info_1 == "tester@example.com"
    assert auth_info_2 is None


def test_normalize_login_error_handles_cloudflare(monkeypatch: pytest.MonkeyPatch) -> None:
    x_client, _ = load_modules(monkeypatch)
    error = x_client._normalize_login_error(RuntimeError("Cloudflare blocked"))
    assert "Cloudflare" in str(error)


def test_register_builtin_tools_adds_x_search(monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules(monkeypatch)
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        workspace=".",
        mode="readonly",
        twitter_email="tester@example.com",
        twitter_password="secret",
        twitter_proxy_url="http://127.0.0.1:7892",
    )
    assert registry.has("x_search")
