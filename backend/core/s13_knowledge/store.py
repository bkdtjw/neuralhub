from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import cast, delete, select, text

from backend.core.s13_knowledge.db_models import (
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
)
from backend.core.s13_knowledge.errors import KnowledgeError
from backend.core.s13_knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    SearchHit,
)
from backend.core.s13_knowledge.store_docs import KnowledgeDocumentStore
from backend.storage.database import SessionFactory, get_db_session


class KnowledgeStore(KnowledgeDocumentStore):
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def get_or_create_default(self) -> KnowledgeBase:
        try:
            existing = await self.get_by_name("默认库")
            if existing is not None:
                return existing
            return await self.create("默认库")
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_DEFAULT_KB_ERROR", str(exc)) from exc

    async def create(self, name: str, description: str = "") -> KnowledgeBase:
        try:
            base = KnowledgeBase(name=_normalize_name(name), description=description)
            async with get_db_session(self._session_factory) as db:
                if await self._name_exists(db, base.name):
                    raise KnowledgeError("KNOWLEDGE_KB_EXISTS", "知识库已存在")
                db.add(KnowledgeBaseRecord(**base.model_dump()))
                await db.commit()
            return base
        except KnowledgeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_KB_CREATE_ERROR", str(exc)) from exc

    async def rename(self, kb_id: str, name: str) -> KnowledgeBase:
        try:
            new_name = _normalize_name(name)
            async with get_db_session(self._session_factory) as db:
                record = await db.get(KnowledgeBaseRecord, kb_id)
                if record is None:
                    raise KnowledgeError("KNOWLEDGE_KB_NOT_FOUND", "知识库不存在")
                if await self._name_exists(db, new_name, exclude_id=kb_id):
                    raise KnowledgeError("KNOWLEDGE_KB_EXISTS", "知识库已存在")
                record.name = new_name
                await db.commit()
                await db.refresh(record)
                return _base(record)
        except KnowledgeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_KB_RENAME_ERROR", str(exc)) from exc

    async def get(self, kb_id: str) -> KnowledgeBase | None:
        try:
            async with get_db_session(self._session_factory) as db:
                record = await db.get(KnowledgeBaseRecord, kb_id)
                return _base(record) if record else None
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_KB_GET_ERROR", str(exc)) from exc

    async def get_by_name(self, name: str) -> KnowledgeBase | None:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.name == name)
                record = (await db.execute(statement)).scalar_one_or_none()
                return _base(record) if record else None
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_KB_GET_ERROR", str(exc)) from exc

    async def list_bases(self) -> list[KnowledgeBase]:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.created_at)
                return [_base(record) for record in (await db.execute(statement)).scalars().all()]
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_KB_LIST_ERROR", str(exc)) from exc

    async def delete_base(self, kb_id: str) -> bool:
        # 显式按 kb_id 清 chunk 与文档再删 base，不依赖 FK 级联是否落库（kb_chunks.kb_id 无 FK）。
        try:
            async with get_db_session(self._session_factory) as db:
                record = await db.get(KnowledgeBaseRecord, kb_id)
                if record is None:
                    return False
                await db.execute(
                    delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.kb_id == kb_id)
                )
                await db.execute(
                    delete(KnowledgeDocumentRecord).where(KnowledgeDocumentRecord.kb_id == kb_id)
                )
                await db.delete(record)
                await db.commit()
                return True
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_KB_DELETE_ERROR", str(exc)) from exc

    async def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                for chunk in chunks:
                    db.add(_chunk_record(chunk))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_CHUNK_ADD_ERROR", str(exc)) from exc

    async def search(self, kb_id: str, query_embedding: list[float], top_k: int) -> list[SearchHit]:
        try:
            async with get_db_session(self._session_factory) as db:
                await db.execute(text("SET LOCAL ivfflat.probes = 100"))
                indexed_embedding = cast(KnowledgeChunkRecord.embedding, HALFVEC(2048))
                indexed_query = cast(query_embedding, HALFVEC(2048))
                distance = indexed_embedding.cosine_distance(indexed_query).label("distance")
                statement = (
                    select(KnowledgeChunkRecord, KnowledgeDocumentRecord.filename, distance)
                    .join(
                        KnowledgeDocumentRecord,
                        KnowledgeDocumentRecord.id == KnowledgeChunkRecord.doc_id,
                    )
                    .where(KnowledgeChunkRecord.kb_id == kb_id)
                    .order_by(distance)
                    .limit(max(top_k, 1))
                )
                rows = (await db.execute(statement)).all()
            return [
                _hit(record, filename, float(distance or 0.0))
                for record, filename, distance in rows
            ]
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_SEARCH_ERROR", str(exc)) from exc

    @staticmethod
    async def _name_exists(db: object, name: str, exclude_id: str = "") -> bool:
        statement = select(KnowledgeBaseRecord.id).where(KnowledgeBaseRecord.name == name)
        if exclude_id:
            statement = statement.where(KnowledgeBaseRecord.id != exclude_id)
        return (await db.execute(statement)).scalar_one_or_none() is not None


def _normalize_name(name: str) -> str:
    normalized = " ".join(name.strip().split())[:50]
    if not normalized:
        raise KnowledgeError("KNOWLEDGE_KB_NAME_EMPTY", "知识库名称不能为空")
    return normalized


def _base(record: KnowledgeBaseRecord) -> KnowledgeBase:
    return KnowledgeBase.model_validate(record.__dict__)


def _chunk_record(chunk: KnowledgeChunk) -> KnowledgeChunkRecord:
    return KnowledgeChunkRecord(
        id=chunk.id,
        kb_id=chunk.kb_id,
        doc_id=chunk.doc_id,
        content=chunk.content,
        embedding=chunk.embedding,
        source=chunk.source,
        page_num=chunk.page_num,
        chunk_index=chunk.chunk_index,
        metadata_json=_metadata_json(chunk.metadata),
        created_at=datetime.utcnow(),
    )


def _hit(record: KnowledgeChunkRecord, filename: str, distance: float) -> SearchHit:
    return SearchHit(
        content=record.content,
        score=1.0 - distance,
        document_name=filename,
        page_num=record.page_num,
        chunk_index=record.chunk_index,
    )


def _metadata_json(metadata: dict[str, object]) -> str:
    import json

    return json.dumps(metadata, ensure_ascii=False)


__all__ = ["KnowledgeStore"]
