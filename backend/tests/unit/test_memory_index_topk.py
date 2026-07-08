from __future__ import annotations

from datetime import datetime, timezone

from backend.common.types import AgentConfig, Message
from backend.core.s01_agent_loop.agent_loop_support import build_llm_request
from backend.core.s06_context_compression import LongTermMemory, MemoryEntry, MemoryIndex
from backend.storage.memory_store import MemoryStore


def _entry(
    entry_id: str,
    keywords: list[str],
    *,
    trigger: str = "淘口令",
    lesson: str = "淘口令要先展开短链",
    hit_count: int = 0,
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id,
        trigger=trigger,
        lesson=lesson,
        keywords=keywords,
        source_session="session-a",
        created_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
        hit_count=hit_count,
    )


def test_memory_index_matches_keywords_without_mutating_hit_count() -> None:
    target = _entry("m1", ["淘口令", "短链"])
    store = LongTermMemory(entries=[target, _entry("m2", ["飞书"])])
    index = MemoryIndex(store)

    matches = index.match("帮我看下这个淘口令 ¥abc¥", limit=5)

    assert matches == [target]
    # 召回不再自增 hit_count：召回权重须由持久化的命中计数提供（E4）
    assert target.hit_count == 0


def test_memory_index_hit_count_boosts_topk() -> None:
    old_winner = _entry("m1", ["淘口令", "商品"], hit_count=20)
    exact = _entry("m2", ["淘口令", "短链"])
    index = MemoryIndex(LongTermMemory(entries=[exact, old_winner]))

    matches = index.match("淘口令需要处理", limit=1)

    assert matches == [old_winner]


def test_build_llm_request_injects_memory_messages() -> None:
    index = MemoryIndex(LongTermMemory(entries=[_entry("m1", ["淘口令"])]))

    request = build_llm_request(
        AgentConfig(model="model", system_prompt="stable"),
        [Message(role="system", content="stable"), Message(role="user", content="处理淘口令")],
        [],
        memory_index=index,
    )

    assert len(request.memory_messages) == 1
    assert "[长期记忆]" in request.memory_messages[0].content
    assert "淘口令要先展开短链" in request.memory_messages[0].content


def test_memory_store_saves_and_loads_json(tmp_path) -> None:
    path = tmp_path / "experiences.json"
    store = MemoryStore(str(path))
    memory = LongTermMemory(entries=[_entry("m1", ["淘口令"])])

    store.save(memory)
    loaded = store.load()

    assert loaded.entries == memory.entries
