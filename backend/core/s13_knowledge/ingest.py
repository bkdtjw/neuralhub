from __future__ import annotations

import asyncio
from pathlib import Path

from backend.core.s13_knowledge.chunker import split_text
from backend.core.s13_knowledge.embedder import BATCH_SIZE, EmbeddingAdapter
from backend.core.s13_knowledge.errors import KnowledgeError
from backend.core.s13_knowledge.models import (
    IngestRequest,
    IngestResult,
    KnowledgeChunk,
    KnowledgeDocument,
)
from backend.core.s13_knowledge.parser import parse_document, validate_file
from backend.core.s13_knowledge.store import KnowledgeStore


class KnowledgeIngestor:
    def __init__(self, store: KnowledgeStore, embedder: EmbeddingAdapter) -> None:
        self._store = store
        self._embedder = embedder

    async def ingest(self, request: IngestRequest) -> IngestResult:
        document = _document_for(request)
        # 幂等 upsert：同名文件重入库=替换而非追加，杜绝崩溃重试造成的重复文档/向量。
        existing = await self._store.get_document_by(request.kb_id, document.filename)
        if existing is not None:
            await self._store.delete_document(existing.id)
        await self._store.create_document(document)
        try:
            # parse+split 纯 CPU（pypdf 逐页 extract 大文件数十秒），放到线程执行，
            # 避免冻结事件循环拖停 sub_worker 心跳续租与 API 主进程 WS/HTTP 调度。
            chunks = await asyncio.to_thread(_parse_and_split, request.file_path)
        except Exception as exc:  # noqa: BLE001
            return await self._finish(document, "failed", 0, 0, str(exc))
        if not chunks:
            return await self._finish(document, "empty", 0, 0, "")
        try:
            built_chunks, error = await self._embed_chunks(document, chunks)
            if built_chunks:
                await self._store.add_chunks(built_chunks)
            status = "partial" if error else "ready"
            return await self._finish(document, status, len(built_chunks), len(chunks), error)
        except Exception as exc:  # noqa: BLE001
            return await self._finish(document, "failed", 0, len(chunks), str(exc))

    async def _embed_chunks(
        self,
        document: KnowledgeDocument,
        texts: list[str],
    ) -> tuple[list[KnowledgeChunk], str]:
        built: list[KnowledgeChunk] = []
        failures: list[str] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                vectors = await self._embedder.embed(batch)
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc))
                continue
            for offset, vector in enumerate(vectors):
                index = start + offset
                built.append(
                    KnowledgeChunk(
                        kb_id=document.kb_id,
                        doc_id=document.id,
                        content=texts[index],
                        embedding=vector,
                        source=document.filename,
                        chunk_index=index,
                    )
                )
        return built, "; ".join(failures)

    async def _finish(
        self,
        document: KnowledgeDocument,
        status: str,
        chunk_count: int,
        total_chunks: int,
        error: str,
    ) -> IngestResult:
        updated = document.model_copy(
            update={"status": status, "chunk_count": chunk_count, "error": error}
        )
        await self._store.update_document(updated)
        return IngestResult(
            kb_id=document.kb_id,
            document_id=document.id,
            status=updated.status,
            chunk_count=chunk_count,
            total_chunks=total_chunks,
            error=error,
        )


def _parse_and_split(path: Path) -> list[str]:
    # 同步 parse+split 合并成一个函数，供 asyncio.to_thread 在工作线程整体执行。
    text = parse_document(path)
    return split_text(text)


def _document_for(request: IngestRequest) -> KnowledgeDocument:
    path = Path(request.file_path)
    try:
        file_type = validate_file(path)
    except KnowledgeError:
        file_type = path.suffix.lower().lstrip(".")
    return KnowledgeDocument(
        kb_id=request.kb_id,
        filename=request.original_name or path.name,
        file_type=file_type,
        file_size=path.stat().st_size if path.exists() else 0,
    )


__all__ = ["KnowledgeIngestor"]
