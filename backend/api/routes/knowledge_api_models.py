from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class KnowledgeBaseCreateRequest(BaseModel):
    name: str


class KnowledgeBaseRenameRequest(BaseModel):
    name: str


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: datetime
    document_count: int = 0
    chunk_count: int = 0
    latest_document_at: datetime | None = None


class KnowledgeBaseListResponse(BaseModel):
    bases: list[KnowledgeBaseResponse]


class KnowledgeDocumentResponse(BaseModel):
    id: str
    kb_id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str
    error: str = ""
    created_at: datetime


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentResponse]


class KnowledgeDeleteResponse(BaseModel):
    deleted: bool
    id: str


class KnowledgeStatusResponse(BaseModel):
    queue_ready: bool
    feishu_configured: bool
    knowledge_ready: bool


class KnowledgeUploadResponse(BaseModel):
    task_id: str
    kb_id: str
    file_count: int
    message: str


KnowledgeStatus = Literal["processing", "ready", "partial", "failed", "empty"]


__all__ = [
    "KnowledgeBaseCreateRequest",
    "KnowledgeBaseListResponse",
    "KnowledgeBaseRenameRequest",
    "KnowledgeBaseResponse",
    "KnowledgeDeleteResponse",
    "KnowledgeDocumentListResponse",
    "KnowledgeDocumentResponse",
    "KnowledgeStatusResponse",
    "KnowledgeUploadResponse",
]
