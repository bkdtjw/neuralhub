from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.api.routes.knowledge import (
    delete_knowledge_base,
    delete_knowledge_document,
)
from backend.core.s13_knowledge.db_models import (
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
)
from backend.core.s13_knowledge.models import KnowledgeChunk, KnowledgeDocument
from backend.core.s13_knowledge.store import KnowledgeStore
from backend.storage.database import SessionFactory

pytestmark = pytest.mark.asyncio


def _embedding() -> list[float]:
    # 2048 维占位向量：删除路径不检索，只需满足 NOT NULL 的 Vector(2048)。
    return [0.1] * 2048


async def _add_doc_with_chunks(
    store: KnowledgeStore,
    kb_id: str,
    filename: str,
    chunk_count: int,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(kb_id=kb_id, filename=filename, file_type="txt")
    await store.create_document(doc)
    await store.add_chunks(
        [
            KnowledgeChunk(
                kb_id=kb_id,
                doc_id=doc.id,
                content=f"{filename}-{index}",
                embedding=_embedding(),
                chunk_index=index,
            )
            for index in range(chunk_count)
        ]
    )
    return doc


async def _doc_count(session_factory: SessionFactory, kb_id: str) -> int:
    async with session_factory() as db:
        result = await db.execute(
            select(func.count())
            .select_from(KnowledgeDocumentRecord)
            .where(KnowledgeDocumentRecord.kb_id == kb_id)
        )
    return int(result.scalar_one())


async def _chunk_count_for_kb(session_factory: SessionFactory, kb_id: str) -> int:
    async with session_factory() as db:
        result = await db.execute(
            select(func.count())
            .select_from(KnowledgeChunkRecord)
            .where(KnowledgeChunkRecord.kb_id == kb_id)
        )
    return int(result.scalar_one())


async def _chunk_count_for_doc(session_factory: SessionFactory, doc_id: str) -> int:
    async with session_factory() as db:
        result = await db.execute(
            select(func.count())
            .select_from(KnowledgeChunkRecord)
            .where(KnowledgeChunkRecord.doc_id == doc_id)
        )
    return int(result.scalar_one())


async def test_delete_document_removes_doc_and_its_chunks(
    db_session_factory: SessionFactory,
) -> None:
    store = KnowledgeStore(db_session_factory)
    kb = await store.get_or_create_default()
    doc_a = await _add_doc_with_chunks(store, kb.id, "a.txt", 3)
    doc_b = await _add_doc_with_chunks(store, kb.id, "b.txt", 2)

    assert await store.delete_document(doc_a.id) is True

    async with db_session_factory() as db:
        assert await db.get(KnowledgeDocumentRecord, doc_a.id) is None
        assert await db.get(KnowledgeDocumentRecord, doc_b.id) is not None
    # doc_a 的 chunks 随文档级联清除；doc_b 及其 chunks 不受影响。
    assert await _chunk_count_for_doc(db_session_factory, doc_a.id) == 0
    assert await _chunk_count_for_doc(db_session_factory, doc_b.id) == 2
    assert await _chunk_count_for_kb(db_session_factory, kb.id) == 2
    # 删不存在的文档返回 False。
    assert await store.delete_document("does-not-exist") is False


async def test_delete_base_clears_docs_chunks_and_leaves_others(
    db_session_factory: SessionFactory,
) -> None:
    store = KnowledgeStore(db_session_factory)
    target = await store.create("待删库")
    other = await store.create("保留库")
    await _add_doc_with_chunks(store, target.id, "t1.txt", 2)
    await _add_doc_with_chunks(store, target.id, "t2.txt", 3)
    keep_doc = await _add_doc_with_chunks(store, other.id, "k1.txt", 4)

    assert await store.delete_base(target.id) is True

    # 目标库：库本身、文档、chunks 全清。
    assert await store.get(target.id) is None
    assert await _doc_count(db_session_factory, target.id) == 0
    assert await _chunk_count_for_kb(db_session_factory, target.id) == 0
    # 其它库：库、文档、chunks 原样保留。
    assert await store.get(other.id) is not None
    assert await _doc_count(db_session_factory, other.id) == 1
    assert await _chunk_count_for_kb(db_session_factory, other.id) == 4
    assert await _chunk_count_for_doc(db_session_factory, keep_doc.id) == 4
    # 删不存在的库返回 False。
    assert await store.delete_base("does-not-exist") is False


async def test_delete_routes_forward_and_report_404(
    db_session_factory: SessionFactory,
) -> None:
    store = KnowledgeStore(db_session_factory)
    kb = await store.create("路由删除库")
    doc = await _add_doc_with_chunks(store, kb.id, "route.txt", 2)

    doc_result = await delete_knowledge_document(doc.id)
    assert doc_result.deleted is True
    assert doc_result.id == doc.id
    assert await _chunk_count_for_doc(db_session_factory, doc.id) == 0

    base_result = await delete_knowledge_base(kb.id)
    assert base_result.deleted is True
    assert base_result.id == kb.id
    assert await store.get(kb.id) is None

    # 缺失资源经服务转发后由路由报 404。
    with pytest.raises(HTTPException) as doc_missing:
        await delete_knowledge_document("does-not-exist")
    assert doc_missing.value.status_code == 404
    with pytest.raises(HTTPException) as base_missing:
        await delete_knowledge_base("does-not-exist")
    assert base_missing.value.status_code == 404
