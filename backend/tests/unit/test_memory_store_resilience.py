from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest_asyncio

from backend.core.s05_skills.runtime import AgentRuntime
from backend.core.s06_context_compression import LongTermMemory, MemoryEntry, MemoryIndex
from backend.storage.memory_store import MemoryStore


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存/tmp_path 单测，跳过 PostgresContainer。
    yield


def _entry() -> MemoryEntry:
    return MemoryEntry(
        id="m1",
        trigger="淘口令",
        lesson="淘口令要先展开短链",
        keywords=["淘口令"],
        source_session="session-a",
        created_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
    )


def test_load_corrupt_file_degrades_and_quarantines(tmp_path) -> None:
    path = tmp_path / "experiences.json"
    path.write_text("{ this is not valid json ", encoding="utf-8")
    store = MemoryStore(str(path))

    memory = store.load()  # 必须不抛异常

    assert isinstance(memory, LongTermMemory)
    assert memory.entries == []
    # 坏文件被改名留档，原路径清空
    assert not path.exists()
    corrupt = tmp_path / "experiences.json.corrupt"
    assert corrupt.exists()
    assert corrupt.read_text(encoding="utf-8") == "{ this is not valid json "


def test_load_missing_file_returns_empty_without_quarantine(tmp_path) -> None:
    path = tmp_path / "experiences.json"
    store = MemoryStore(str(path))

    memory = store.load()

    assert memory.entries == []
    assert not (tmp_path / "experiences.json.corrupt").exists()


def test_save_writes_atomically_and_roundtrips(tmp_path) -> None:
    path = tmp_path / "experiences.json"
    store = MemoryStore(str(path))
    memory = LongTermMemory(entries=[_entry()])

    store.save(memory)

    # 无残留 tmp 文件，内容完整可回读
    assert not (tmp_path / "experiences.tmp").exists()
    assert path.exists()
    assert store.load().entries == memory.entries


def test_save_goes_through_tmp_then_os_replace(tmp_path, monkeypatch) -> None:
    path = tmp_path / "experiences.json"
    store = MemoryStore(str(path))
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    store.save(LongTermMemory(entries=[_entry()]))

    assert len(calls) == 1
    src, dst = calls[0]
    assert src.endswith("experiences.tmp")
    assert dst.endswith("experiences.json")


def test_build_memory_index_degrades_when_load_raises(monkeypatch) -> None:
    def boom(self: MemoryStore) -> LongTermMemory:
        raise RuntimeError("corrupt memory backend")

    monkeypatch.setattr(MemoryStore, "load", boom)

    index = AgentRuntime._build_memory_index()  # noqa: SLF001

    assert isinstance(index, MemoryIndex)
    assert index.store.entries == []
