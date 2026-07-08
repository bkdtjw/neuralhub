from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.core.s13_knowledge import IngestRequest, KnowledgeService, SearchRequest
from backend.core.s13_knowledge.db_models import (
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
)
from backend.core.s13_knowledge.models import KnowledgeDocument
from backend.core.s13_knowledge.store import KnowledgeStore
from backend.storage.database import SessionFactory


class HashEmbedder:
    # mock embedder：本地散列成 2048 维向量，不发真实向量请求。
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector(text) for text in texts]


def _vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(digest[index % len(digest)]) for index in range(2048)]


def _two_chunk_text(marker: str) -> str:
    # 两段各 500 字，合并后超过 MAX_CHUNK_CHARS(800) → 稳定切成 2 个 chunk。
    return f"{marker * 500}\n\n{marker * 500}"


async def _counts(session_factory: SessionFactory, kb_id: str) -> tuple[int, int]:
    async with session_factory() as db:
        docs = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeDocumentRecord)
                .where(KnowledgeDocumentRecord.kb_id == kb_id)
            )
        ).scalar_one()
        chunks = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeChunkRecord)
                .where(KnowledgeChunkRecord.kb_id == kb_id)
            )
        ).scalar_one()
    return int(docs), int(chunks)


async def _chunks_for_doc(session_factory: SessionFactory, doc_id: str) -> int:
    async with session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeChunkRecord)
                .where(KnowledgeChunkRecord.doc_id == doc_id)
            )
        ).scalar_one()
    return int(count)


@pytest.mark.asyncio
async def test_reingest_same_file_replaces_and_clears_old_chunks(
    db_session_factory: SessionFactory,
    tmp_path: Path,
) -> None:
    service = KnowledgeService.from_session_factory(db_session_factory, HashEmbedder())
    kb = await service.get_or_create_default_kb()
    path = tmp_path / "manual.txt"
    path.write_text(_two_chunk_text("A"), encoding="utf-8")

    first = await service.ingest_document(IngestRequest(file_path=path, kb_id=kb.id))
    assert first.status == "ready"
    assert await _counts(db_session_factory, kb.id) == (1, 2)

    # 模拟崩溃/超时后 recover 重入队：同一 (kb_id, filename) 再次入库。
    second = await service.ingest_document(IngestRequest(file_path=path, kb_id=kb.id))

    # 文档数不翻倍：旧文档被删，只留一份新文档；chunks 也未累加。
    assert await _counts(db_session_factory, kb.id) == (1, 2)
    assert second.document_id != first.document_id
    async with db_session_factory() as db:
        assert await db.get(KnowledgeDocumentRecord, first.document_id) is None
    # 旧 chunks 已随旧文档级联清除，新 chunks 全部挂在新文档下。
    assert await _chunks_for_doc(db_session_factory, first.document_id) == 0
    assert await _chunks_for_doc(db_session_factory, second.document_id) == 2
    # 检索命中的是替换后的新文档。
    hits = await service.search(
        SearchRequest(query=_two_chunk_text("A"), kb_id=kb.id, top_k=5)
    )
    assert hits
    assert all(hit.document_name == "manual.txt" for hit in hits)


@pytest.mark.asyncio
async def test_different_filenames_stay_independent(
    db_session_factory: SessionFactory,
    tmp_path: Path,
) -> None:
    service = KnowledgeService.from_session_factory(db_session_factory, HashEmbedder())
    kb = await service.get_or_create_default_kb()
    path_a = tmp_path / "alpha.txt"
    path_b = tmp_path / "beta.txt"
    path_a.write_text(_two_chunk_text("A"), encoding="utf-8")
    path_b.write_text(_two_chunk_text("B"), encoding="utf-8")

    await service.ingest_document(IngestRequest(file_path=path_a, kb_id=kb.id))
    beta = await service.ingest_document(IngestRequest(file_path=path_b, kb_id=kb.id))
    assert await _counts(db_session_factory, kb.id) == (2, 4)

    # 重入库 alpha.txt：只替换 alpha，beta 文档与其 chunks 原样保留。
    await service.ingest_document(IngestRequest(file_path=path_a, kb_id=kb.id))
    assert await _counts(db_session_factory, kb.id) == (2, 4)
    async with db_session_factory() as db:
        assert await db.get(KnowledgeDocumentRecord, beta.document_id) is not None
    assert await _chunks_for_doc(db_session_factory, beta.document_id) == 2


@pytest.mark.asyncio
async def test_get_and_delete_document_store_helpers(
    db_session_factory: SessionFactory,
) -> None:
    store = KnowledgeStore(db_session_factory)
    kb = await store.get_or_create_default()

    # 缺失场景：查不到返回 None，删不存在返回 False。
    assert await store.get_document_by(kb.id, "missing.txt") is None
    assert await store.delete_document("does-not-exist") is False

    doc = KnowledgeDocument(kb_id=kb.id, filename="notes.txt", file_type="txt")
    await store.create_document(doc)
    found = await store.get_document_by(kb.id, "notes.txt")
    assert found is not None
    assert found.id == doc.id

    assert await store.delete_document(doc.id) is True
    assert await store.get_document_by(kb.id, "notes.txt") is None
