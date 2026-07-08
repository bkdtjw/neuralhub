from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from backend.api.middleware.auth import verify_token
from backend.api.routes.knowledge_api_models import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseRenameRequest,
    KnowledgeBaseResponse,
    KnowledgeDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeStatusResponse,
    KnowledgeUploadResponse,
)
from backend.api.routes.knowledge_upload import save_upload_batch
from backend.common.utils.id_generator import generate_id
from backend.config.settings import settings
from backend.core.s13_knowledge import (
    KnowledgeBase,
    KnowledgeBaseStats,
    KnowledgeDocument,
    KnowledgeService,
)

router = APIRouter(
    prefix="/api/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(verify_token)],
)


@router.get("/status", response_model=KnowledgeStatusResponse)
async def get_knowledge_status(request: Request) -> KnowledgeStatusResponse:
    try:
        return KnowledgeStatusResponse(
            queue_ready=getattr(request.app.state, "task_queue", None) is not None,
            feishu_configured=bool(settings.feishu_app_id and settings.feishu_app_secret),
            knowledge_ready=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_STATUS_ERROR", str(exc)) from exc


@router.get("/bases", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases() -> KnowledgeBaseListResponse:
    try:
        stats = await KnowledgeService().list_kb_stats()
        return KnowledgeBaseListResponse(bases=[_stats_response(item) for item in stats])
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_BASE_LIST_ERROR", str(exc)) from exc


@router.post("/bases", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(body: KnowledgeBaseCreateRequest) -> KnowledgeBaseResponse:
    try:
        kb = await KnowledgeService().create_kb(body.name)
        return _base_response(kb)
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_BASE_CREATE_ERROR", str(exc), 400) from exc


@router.patch("/bases/{kb_id}", response_model=KnowledgeBaseResponse)
async def rename_knowledge_base(
    kb_id: str,
    body: KnowledgeBaseRenameRequest,
) -> KnowledgeBaseResponse:
    try:
        kb = await KnowledgeService().rename_kb(kb_id, body.name)
        return _base_response(kb)
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_BASE_RENAME_ERROR", str(exc), 400) from exc


@router.get("/bases/{kb_id}/documents", response_model=KnowledgeDocumentListResponse)
async def list_knowledge_documents(kb_id: str) -> KnowledgeDocumentListResponse:
    try:
        service = KnowledgeService()
        if await service.get_kb(kb_id) is None:
            raise HTTPException(status_code=404, detail={"message": "知识库不存在"})
        docs = await service.list_documents(kb_id)
        return KnowledgeDocumentListResponse(documents=[_document_response(item) for item in docs])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_DOCUMENT_LIST_ERROR", str(exc)) from exc


@router.post("/bases/{kb_id}/documents", response_model=KnowledgeUploadResponse)
async def upload_knowledge_documents(
    kb_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
) -> KnowledgeUploadResponse:
    try:
        queue = getattr(request.app.state, "task_queue", None)
        if queue is None:
            raise HTTPException(status_code=503, detail={"message": "入库队列不可用"})
        service = KnowledgeService()
        if await service.get_kb(kb_id) is None:
            raise HTTPException(status_code=404, detail={"message": "知识库不存在"})
        task_id = f"kb-local-{generate_id()}"
        saved = await save_upload_batch(kb_id, task_id, files)
        await queue.submit(
            task_id,
            {
                "kind": "knowledge_ingest_local_batch",
                "kb_id": kb_id,
                "files": [item.model_dump() for item in saved],
            },
            timeout_seconds=3600.0,
            max_retries=1,
        )
        return KnowledgeUploadResponse(
            task_id=task_id,
            kb_id=kb_id,
            file_count=len(saved),
            message=f"收到 {len(saved)} 个文件，正在入库",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_DOCUMENT_UPLOAD_ERROR", str(exc), 400) from exc


@router.delete("/bases/{kb_id}", response_model=KnowledgeDeleteResponse)
async def delete_knowledge_base(kb_id: str) -> KnowledgeDeleteResponse:
    try:
        deleted = await KnowledgeService().delete_kb(kb_id)
        if not deleted:
            raise HTTPException(status_code=404, detail={"message": "知识库不存在"})
        return KnowledgeDeleteResponse(deleted=deleted, id=kb_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_BASE_DELETE_ERROR", str(exc)) from exc


@router.delete("/documents/{doc_id}", response_model=KnowledgeDeleteResponse)
async def delete_knowledge_document(doc_id: str) -> KnowledgeDeleteResponse:
    try:
        deleted = await KnowledgeService().delete_document(doc_id)
        if not deleted:
            raise HTTPException(status_code=404, detail={"message": "文档不存在"})
        return KnowledgeDeleteResponse(deleted=deleted, id=doc_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _server_error("KNOWLEDGE_DOCUMENT_DELETE_ERROR", str(exc)) from exc


def _base_response(base: KnowledgeBase) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        id=base.id,
        name=base.name,
        description=base.description,
        created_at=base.created_at,
    )


def _stats_response(stats: KnowledgeBaseStats) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(**stats.model_dump())


def _document_response(document: KnowledgeDocument) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(**document.model_dump())


def _server_error(code: str, message: str, status_code: int = 500) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


__all__ = ["router"]
