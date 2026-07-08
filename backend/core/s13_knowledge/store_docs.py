from __future__ import annotations

from sqlalchemy import select

from backend.core.s13_knowledge.db_models import KnowledgeDocumentRecord
from backend.core.s13_knowledge.errors import KnowledgeError
from backend.core.s13_knowledge.models import KnowledgeDocument
from backend.storage.database import SessionFactory, get_db_session


class KnowledgeDocumentStore:
    """文档记录存取（含幂等 upsert 所需的查/删）。混入 KnowledgeStore。"""

    _session_factory: SessionFactory | None

    async def create_document(self, document: KnowledgeDocument) -> KnowledgeDocument:
        try:
            async with get_db_session(self._session_factory) as db:
                db.add(KnowledgeDocumentRecord(**document.model_dump()))
                await db.commit()
            return document
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_CREATE_ERROR", str(exc)) from exc

    async def get_document_by(self, kb_id: str, filename: str) -> KnowledgeDocument | None:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = (
                    select(KnowledgeDocumentRecord)
                    .where(
                        KnowledgeDocumentRecord.kb_id == kb_id,
                        KnowledgeDocumentRecord.filename == filename,
                    )
                    .order_by(KnowledgeDocumentRecord.created_at.desc())
                    .limit(1)
                )
                record = (await db.execute(statement)).scalars().first()
                return KnowledgeDocument.model_validate(record.__dict__) if record else None
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_GET_ERROR", str(exc)) from exc

    async def update_document(self, document: KnowledgeDocument) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                record = await db.get(KnowledgeDocumentRecord, document.id)
                if record is None:
                    return
                record.status = document.status
                record.chunk_count = document.chunk_count
                record.error = document.error
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_UPDATE_ERROR", str(exc)) from exc

    async def delete_document(self, doc_id: str) -> bool:
        # kb_chunks.doc_id ON DELETE CASCADE：删文档记录即级联清除其 chunks。
        try:
            async with get_db_session(self._session_factory) as db:
                record = await db.get(KnowledgeDocumentRecord, doc_id)
                if record is None:
                    return False
                await db.delete(record)
                await db.commit()
                return True
        except Exception as exc:  # noqa: BLE001
            raise KnowledgeError("KNOWLEDGE_DOCUMENT_DELETE_ERROR", str(exc)) from exc


__all__ = ["KnowledgeDocumentStore"]
