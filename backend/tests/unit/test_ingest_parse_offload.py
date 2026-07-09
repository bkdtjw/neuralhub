from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from backend.core.s13_knowledge import ingest as ingest_module
from backend.core.s13_knowledge.ingest import KnowledgeIngestor
from backend.core.s13_knowledge.models import IngestRequest, KnowledgeChunk, KnowledgeDocument


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存单测，跳过 PostgresContainer 避免拖慢。
    yield


class _FakeStore:
    # 纯内存 store，只实现 KnowledgeIngestor.ingest 用到的接口。
    def __init__(self) -> None:
        self.documents: dict[str, KnowledgeDocument] = {}
        self.chunks: list[KnowledgeChunk] = []

    async def get_document_by(self, kb_id: str, filename: str) -> KnowledgeDocument | None:
        for doc in self.documents.values():
            if doc.kb_id == kb_id and doc.filename == filename:
                return doc
        return None

    async def delete_document(self, doc_id: str) -> bool:
        return self.documents.pop(doc_id, None) is not None

    async def create_document(self, document: KnowledgeDocument) -> None:
        self.documents[document.id] = document

    async def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        self.chunks.extend(chunks)

    async def update_document(self, document: KnowledgeDocument) -> None:
        self.documents[document.id] = document


class _FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


@pytest.mark.asyncio
async def test_parse_offloaded_to_thread_keeps_event_loop_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 用一个 time.sleep 型同步解析模拟大 PDF 的纯 CPU 阻塞，记录其执行线程。
    block_seconds = 0.3
    main_thread_id = threading.get_ident()
    parse_thread: dict[str, int] = {}

    def blocking_parse(path: Path) -> str:
        parse_thread["id"] = threading.get_ident()
        time.sleep(block_seconds)
        return "alpha paragraph\n\nbeta paragraph"

    monkeypatch.setattr(ingest_module, "parse_document", blocking_parse)
    monkeypatch.setattr(ingest_module, "split_text", lambda _text: ["alpha", "beta"])

    path = tmp_path / "large.pdf"
    path.write_text("placeholder", encoding="utf-8")
    ingestor = KnowledgeIngestor(_FakeStore(), _FakeEmbedder())
    request = IngestRequest(file_path=path, kb_id="kb-1")

    # 计时协程：解析阻塞期间若事件循环未冻结，它应持续按 10ms 间隔推进。
    ticks = 0
    stop = asyncio.Event()

    async def ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.01)

    ticker_task = asyncio.create_task(ticker())
    result = await ingestor.ingest(request)
    stop.set()
    await ticker_task

    # 主证据（确定性）：解析跑在工作线程，而非事件循环所在的主线程。
    assert parse_thread["id"] != main_thread_id
    # 佐证：0.3s 阻塞里 ticker 推进了很多次（若冻结则≈0），证明循环未假死。
    assert ticks >= 5
    # 语义不变：解析+切分成功后照常入库。
    assert result.status == "ready"
    assert result.chunk_count == 2


@pytest.mark.asyncio
async def test_parse_or_split_exception_marks_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # to_thread 把线程内异常原样抛回；split_text 异常也应归入 failed 分支。
    def boom_split(_text: str) -> list[str]:
        raise RuntimeError("split blew up")

    monkeypatch.setattr(ingest_module, "parse_document", lambda _path: "text body")
    monkeypatch.setattr(ingest_module, "split_text", boom_split)

    path = tmp_path / "doc.txt"
    path.write_text("placeholder", encoding="utf-8")
    ingestor = KnowledgeIngestor(_FakeStore(), _FakeEmbedder())

    result = await ingestor.ingest(IngestRequest(file_path=path, kb_id="kb-1"))

    assert result.status == "failed"
    assert "split blew up" in result.error
