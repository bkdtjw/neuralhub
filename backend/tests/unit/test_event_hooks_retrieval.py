from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from backend.core.s07_task_system.event_hooks import (
    EventHook,
    HookSources,
    HookTwitterConfig,
    TwitterQuery,
    build_account_query,
    build_topic_query,
    retrieve_twitter,
)


@pytest.fixture(autouse=True)
def bind_test_database() -> None:
    return None


@dataclass
class FakeTweet:
    author_name: str = "News Desk"
    author_handle: str = "NewsDesk"
    text: str = "Fable 5 unlock window moved"
    likes: int = 0
    retweets: int = 0
    created_at: str = "2026-06-27T00:00:00Z"
    url: str = "https://x.com/newsdesk/status/1"


@dataclass
class FakeSearch:
    account_posts: Sequence[FakeTweet] = ()
    topic_posts: Sequence[FakeTweet] = ()
    fail_account: bool = False
    fail_topic: bool = False
    queries: list[TwitterQuery] = field(default_factory=list)

    async def __call__(self, query: TwitterQuery) -> Sequence[FakeTweet]:
        self.queries.append(query)
        if "from:" in query.query:
            if self.fail_account:
                raise RuntimeError("account lane unavailable")
            return self.account_posts
        if self.fail_topic:
            raise RuntimeError("topic lane unavailable")
        return self.topic_posts


def _hook(
    accounts: list[str] | None = None,
    keywords: list[str] | None = None,
) -> EventHook:
    return EventHook(
        id="hook-1",
        name="Launch Watch",
        twitter=HookTwitterConfig(accounts=accounts or [], keywords=keywords or []),
        sources=HookSources(),
        cadence_minutes=45,
        materiality=60,
        enabled=True,
        created_at="2026-06-27T00:00:00Z",
    )


def test_query_builders_format_account_and_topic_lanes() -> None:
    assert build_account_query(["@Alice", " bob "]) == "(from:alice OR from:bob)"
    assert (
        build_account_query(["axios"], ["Fable 5", "Fable5"])
        == '(from:axios) ("Fable 5" OR Fable5)'
    )
    topic_query = build_topic_query(["Fable 5", "unlock"], 30)

    assert topic_query == '("Fable 5" OR unlock) min_faves:30'


def test_query_builder_escapes_operators_and_quotes() -> None:
    # 内嵌双引号剥除；含 `:` 与以 `-` 开头的词整体加引号，失去 X 查询操作符语义。
    query = build_topic_query(['say "hi"', "since:2026-01-01", "-scam"], 30)

    assert query == '("say hi" OR "since:2026-01-01" OR "-scam") min_faves:30'
    # account lane 的 topic 子句同样走 _format_keyword。
    account = build_account_query(["axios"], ["since:2026-01-01"])
    assert account == '(from:axios) ("since:2026-01-01")'


@pytest.mark.asyncio
async def test_retrieve_twitter_maps_lanes_matches_and_engagement() -> None:
    fake = FakeSearch(
        account_posts=(
            FakeTweet(
                author_handle="NewsDesk",
                text="Account update",
                likes=4,
                retweets=6,
                url="https://x.com/newsdesk/status/101",
            ),
        ),
        topic_posts=(
            FakeTweet(
                author_handle="OtherDesk",
                text="Fable 5 unlock window moved",
                likes=30,
                retweets=2,
                url="https://x.com/other/status/102",
            ),
        ),
    )

    outcome = await retrieve_twitter(
        _hook(accounts=["newsdesk"], keywords=["Fable 5", "unlock"]),
        fake,
    )
    signals = outcome.signals

    assert outcome.ok is True
    assert [signal.lane for signal in signals] == ["account", "topic"]
    assert fake.queries[0].query == '(from:newsdesk) ("Fable 5" OR unlock)'
    assert fake.queries[1].query == '("Fable 5" OR unlock) min_faves:30'
    assert signals[0].source == "twitter"
    assert signals[0].author == "newsdesk"
    assert signals[0].matched == ["newsdesk"]
    assert signals[0].engagement == 10
    assert signals[1].author == "otherdesk"
    assert signals[1].matched == ["Fable 5", "unlock"]
    assert signals[1].engagement == 32


@pytest.mark.asyncio
async def test_retrieve_twitter_dedupes_same_tweet_id_and_keeps_account_lane() -> None:
    fake = FakeSearch(
        account_posts=(
            FakeTweet(
                author_handle="NewsDesk",
                text="Account first",
                url="https://x.com/newsdesk/status/777",
            ),
        ),
        topic_posts=(
            FakeTweet(
                author_handle="OtherDesk",
                text="Fable 5 moved",
                url="https://twitter.com/other/status/777?ref=feed",
            ),
        ),
    )

    outcome = await retrieve_twitter(
        _hook(accounts=["newsdesk"], keywords=["Fable 5"]),
        fake,
    )
    signals = outcome.signals

    assert outcome.ok is True
    assert len(signals) == 1
    assert signals[0].lane == "account"
    assert signals[0].text == "Account first"
    assert signals[0].matched == ["newsdesk", "Fable 5"]


@pytest.mark.asyncio
async def test_retrieve_twitter_lane_failure_keeps_other_lane() -> None:
    fake = FakeSearch(
        topic_posts=(
            FakeTweet(
                author_handle="TopicDesk",
                text="Fable 5 unlock",
                likes=9,
                retweets=1,
                url="https://x.com/topic/status/303",
            ),
        ),
        fail_account=True,
    )

    outcome = await retrieve_twitter(
        _hook(accounts=["newsdesk"], keywords=["Fable 5"]),
        fake,
    )
    signals = outcome.signals

    # 一条 lane 失败、一条成功 → 部分成功仍算 ok=True，信号照常返回。
    assert outcome.ok is True
    assert len(signals) == 1
    assert signals[0].lane == "topic"
    assert signals[0].matched == ["Fable 5"]
    assert [query.max_results for query in fake.queries] == [25, 25]


@pytest.mark.asyncio
async def test_retrieve_twitter_all_lanes_failed_reports_not_ok() -> None:
    # 两条 lane 都异常 → ok=False（健康灯据此翻红），信号为空。
    fake = FakeSearch(fail_account=True, fail_topic=True)

    outcome = await retrieve_twitter(
        _hook(accounts=["newsdesk"], keywords=["Fable 5"]),
        fake,
    )

    assert outcome.ok is False
    assert outcome.signals == []


@pytest.mark.asyncio
async def test_retrieve_twitter_skips_empty_lanes() -> None:
    topic_only = FakeSearch(topic_posts=(FakeTweet(url="https://x.com/a/status/1"),))
    account_only = FakeSearch(account_posts=(FakeTweet(url="https://x.com/a/status/2"),))

    topic_outcome = await retrieve_twitter(_hook(accounts=[], keywords=["Fable 5"]), topic_only)
    account_outcome = await retrieve_twitter(_hook(accounts=["newsdesk"], keywords=[]), account_only)

    # 没有 lane 因异常失败 → ok=True。
    assert topic_outcome.ok is True and account_outcome.ok is True
    assert len(topic_only.queries) == 1
    assert "from:" not in topic_only.queries[0].query
    assert "min_faves:30" in topic_only.queries[0].query
    assert len(account_only.queries) == 1
    assert account_only.queries[0].query == "(from:newsdesk)"
    assert "min_faves" not in account_only.queries[0].query
