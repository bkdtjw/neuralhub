from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest_asyncio

from backend.core.s06_context_compression import LongTermMemory, MemoryEntry, MemoryIndex


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer。
    yield


def _entry(
    entry_id: str,
    keywords: list[str],
    *,
    hit_count: int = 0,
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id,
        trigger="淘口令",
        lesson="淘口令要先展开短链",
        keywords=keywords,
        source_session="session-a",
        created_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
        hit_count=hit_count,
    )


def test_repeated_match_does_not_accumulate_hit_count() -> None:
    # E4：召回不再自增 hit_count，重复 query 也不会无界累加同一 entry。
    fresh = _entry("m1", ["淘口令", "短链"], hit_count=0)
    warm = _entry("m2", ["淘口令"], hit_count=7)
    index = MemoryIndex(LongTermMemory(entries=[fresh, warm]))

    for _ in range(10):
        index.match("帮我看下这个淘口令 ¥abc¥", limit=5)

    assert fresh.hit_count == 0
    assert warm.hit_count == 7


def test_match_is_idempotent() -> None:
    # 召回无副作用：同一 query 反复调用，结果稳定。
    index = MemoryIndex(
        LongTermMemory(
            entries=[
                _entry("m1", ["淘口令", "短链"]),
                _entry("m2", ["飞书"]),
            ]
        )
    )

    first = index.match("处理淘口令 短链", limit=5)
    second = index.match("处理淘口令 短链", limit=5)

    assert [entry.id for entry in first] == [entry.id for entry in second]


def test_persisted_hit_count_still_boosts_topk() -> None:
    # 召回排序仍受（持久化的）hit_count 影响，top-k 选择不因本次改动回归。
    old_winner = _entry("m1", ["淘口令", "商品"], hit_count=20)
    exact = _entry("m2", ["淘口令", "短链"], hit_count=0)
    index = MemoryIndex(LongTermMemory(entries=[exact, old_winner]))

    matches = index.match("淘口令需要处理", limit=1)

    assert [entry.id for entry in matches] == ["m1"]


def test_topk_tiebreak_orders_by_persisted_hit_count() -> None:
    # 同分时按持久化 hit_count 破平；反复调用次序不变（无自增）。
    lighter = _entry("m1", ["关键词"], hit_count=25)
    heavier = _entry("m2", ["关键词"], hit_count=30)
    index = MemoryIndex(LongTermMemory(entries=[lighter, heavier]))

    matches: list[MemoryEntry] = []
    for _ in range(3):
        matches = index.match("命中关键词", limit=2)

    assert [entry.id for entry in matches] == ["m2", "m1"]
    assert (lighter.hit_count, heavier.hit_count) == (25, 30)


def test_match_respects_limit_and_ordering() -> None:
    entries = [_entry(f"m{i}", ["淘口令"], hit_count=i) for i in range(5)]
    index = MemoryIndex(LongTermMemory(entries=entries))

    matches = index.match("淘口令", limit=2)

    assert len(matches) == 2
    # hit_count 越高排序越靠前（持久化权重）。
    assert [entry.id for entry in matches] == ["m4", "m3"]
