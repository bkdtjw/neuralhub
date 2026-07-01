from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.common.types import Message
from backend.core.s06_context_compression import MemoryEntry
from backend.storage.memory_store import MemoryStore
from backend.storage.session_store import SessionStore

MAX_CONTEXT_CHARS = 6000
MAX_MEMORY_CHARS = 1200


class FeishuSessionRecorderError(Exception):
    """Feishu session recorder error."""


class FeishuRecordConfig(BaseModel):
    model: str = ""
    provider: str = ""
    system_prompt: str = ""
    title: str = "飞书对话"


class FeishuOutboundTextRecord(BaseModel):
    chat_id: str
    text: str
    source: str = "feishu_outbound_text"
    persist_memory: bool = False
    config: FeishuRecordConfig = Field(default_factory=FeishuRecordConfig)


class FeishuOutboundFileRecord(BaseModel):
    chat_id: str
    file_name: str
    file_key: str = ""
    local_path: str = ""
    summary: str = ""
    source: str = "feishu_outbound_file"
    persist_memory: bool = False
    config: FeishuRecordConfig = Field(default_factory=FeishuRecordConfig)


class FeishuSessionRecorder:
    def __init__(
        self,
        store: SessionStore,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self._store = store
        self._memory_store = memory_store or MemoryStore()

    async def record_text(self, record: FeishuOutboundTextRecord) -> None:
        try:
            text = record.text.strip()
            if not record.chat_id.strip() or not text:
                return
            await self._ensure_session(record.chat_id, record.config)
            content = _wrap_context(record.source, _clip(text, MAX_CONTEXT_CHARS))
            await self._store.add_messages(
                record.chat_id,
                [
                    Message(
                        role="user",
                        kind="runtime_context",
                        content=content,
                        provider_metadata=_text_metadata(record),
                    )
                ],
            )
            if record.persist_memory:
                self._remember(record.chat_id, record.source, text)
        except Exception as exc:  # noqa: BLE001
            raise FeishuSessionRecorderError(str(exc)) from exc

    async def record_file(self, record: FeishuOutboundFileRecord) -> None:
        try:
            if not record.chat_id.strip() or not record.file_name.strip():
                return
            await self._ensure_session(record.chat_id, record.config)
            content = _file_context(record)
            await self._store.add_messages(
                record.chat_id,
                [
                    Message(
                        role="user",
                        kind="runtime_context",
                        content=content,
                        provider_metadata=_file_metadata(record),
                    )
                ],
            )
            if record.persist_memory:
                self._remember(record.chat_id, record.source, content)
        except Exception as exc:  # noqa: BLE001
            raise FeishuSessionRecorderError(str(exc)) from exc

    async def _ensure_session(self, chat_id: str, config: FeishuRecordConfig) -> None:
        try:
            await self._store.ensure_session(
                chat_id,
                model=config.model,
                provider=config.provider,
                system_prompt=config.system_prompt,
                title=config.title,
            )
        except Exception as exc:  # noqa: BLE001
            raise FeishuSessionRecorderError(str(exc)) from exc

    def _remember(self, chat_id: str, source: str, text: str) -> None:
        lesson = _clip(text, MAX_MEMORY_CHARS)
        self._memory_store.add(
            MemoryEntry(
                id=uuid4().hex,
                trigger=f"Feishu {source}",
                lesson=lesson,
                keywords=_keywords(text),
                source_session=chat_id,
                created_at=datetime.now(UTC),
            )
        )


def _wrap_context(source: str, text: str) -> str:
    return f"<feishu_outbound_context source=\"{source}\">\n{text}\n</feishu_outbound_context>"


def _file_context(record: FeishuOutboundFileRecord) -> str:
    lines = [
        "我已向当前飞书会话发送一个附件；这是附件元数据记录。",
        f"文件名: {record.file_name}",
    ]
    if record.file_key:
        lines.append(f"file_key: {record.file_key}")
    if record.local_path:
        lines.append(f"本地路径: {record.local_path}")
    if record.summary:
        lines.append("说明: " + _clip(record.summary, MAX_CONTEXT_CHARS))
    lines.append("注意: 这不代表模型已读取附件全文；需要正文时应读取本地路径或走知识库检索。")
    return _wrap_context(record.source, "\n".join(lines))


def _text_metadata(record: FeishuOutboundTextRecord) -> dict[str, object]:
    return {
        "feishu": {
            "source": record.source,
            "message_type": "text",
            "body_status": "inline",
        }
    }


def _file_metadata(record: FeishuOutboundFileRecord) -> dict[str, object]:
    return {
        "feishu": {
            "source": record.source,
            "message_type": "file",
            "file_key": record.file_key,
            "file_name": record.file_name,
            "local_path": record.local_path,
            "body_status": "metadata_only",
        }
    }


def _clip(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}...[已截断]"


def _keywords(text: str) -> list[str]:
    base = ["飞书", "附件", "文件", "字幕", "总结", "关键点", "上下文"]
    tokens = re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for token in [*base, *tokens]:
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(token)
        if len(result) >= 20:
            break
    return result


__all__ = [
    "FeishuOutboundFileRecord",
    "FeishuOutboundTextRecord",
    "FeishuRecordConfig",
    "FeishuSessionRecorder",
    "FeishuSessionRecorderError",
]
