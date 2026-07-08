from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from backend.common.errors import AgentError
from backend.common.types import Message, Session
from backend.storage.database import SessionFactory, get_db_session
from backend.storage.models import MessageRecord, SessionRecord
from backend.storage.serializers import to_message, to_message_record, to_session


class SessionStore:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory

    async def create(self, session: Session, title: str = "", workspace: str = "") -> Session:
        try:
            async with get_db_session(self._session_factory) as db:
                db.add(
                    SessionRecord(
                        id=session.id,
                        title=title,
                        workspace=workspace,
                        model=session.config.model,
                        provider=session.config.provider,
                        system_prompt=session.config.system_prompt,
                        status=session.status,
                        max_tokens=session.config.max_tokens,
                        temperature=session.config.temperature,
                        created_at=session.created_at,
                    )
                )
                for message in session.messages:
                    db.add(to_message_record(session.id, message))
                await db.commit()
            return session.model_copy(update={"title": title, "workspace": workspace})
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_CREATE_ERROR", str(exc)) from exc

    async def get(self, session_id: str) -> Session | None:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = select(SessionRecord).options(selectinload(SessionRecord.messages)).where(SessionRecord.id == session_id)
                record = (await db.execute(statement)).scalar_one_or_none()
                if record is None:
                    return None
                messages = [to_message(item) for item in sorted(record.messages, key=lambda current: (current.timestamp, current.id))]
                return to_session(record, messages)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_GET_ERROR", str(exc)) from exc

    async def list_all(self) -> list[tuple[Session, int]]:
        # 仅聚合消息条数，避免把整张 messages 表读入内存并反序列化 tool_calls/results；
        # 同时排除 sub-agent:{task_id} checkpoint 会话（不在会话列表里展示）。
        try:
            async with get_db_session(self._session_factory) as db:
                statement = (
                    select(SessionRecord, func.count(MessageRecord.id))
                    .outerjoin(MessageRecord, MessageRecord.session_id == SessionRecord.id)
                    .where(SessionRecord.id.notlike("sub-agent:%"))
                    .group_by(SessionRecord.id)
                    .order_by(SessionRecord.created_at.desc())
                )
                rows = (await db.execute(statement)).all()
                return [(to_session(record), count) for record, count in rows]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_LIST_ERROR", str(exc)) from exc

    async def update_title(self, session_id: str, title: str) -> Session | None:
        try:
            async with get_db_session(self._session_factory) as db:
                await db.execute(update(SessionRecord).where(SessionRecord.id == session_id).values(title=title))
                await db.commit()
            return await self.get(session_id)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_UPDATE_TITLE_ERROR", str(exc)) from exc

    async def update_status(self, session_id: str, status: str) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                await db.execute(update(SessionRecord).where(SessionRecord.id == session_id).values(status=status))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_UPDATE_STATUS_ERROR", str(exc)) from exc

    async def delete(self, session_id: str) -> bool:
        try:
            async with get_db_session(self._session_factory) as db:
                result = await db.execute(delete(SessionRecord).where(SessionRecord.id == session_id))
                await db.commit()
                return bool(result.rowcount)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_DELETE_ERROR", str(exc)) from exc

    async def purge_sub_agent_sessions(self, before: datetime) -> int:
        # 回收永不清理的 sub-agent:{task_id} checkpoint 会话；messages 由 FK ondelete=CASCADE 级联删除。
        try:
            async with get_db_session(self._session_factory) as db:
                result = await db.execute(
                    delete(SessionRecord).where(
                        SessionRecord.id.like("sub-agent:%"),
                        SessionRecord.created_at < before,
                    )
                )
                await db.commit()
                return int(result.rowcount or 0)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_PURGE_SUB_AGENT_ERROR", str(exc)) from exc

    async def save_messages(self, session_id: str, messages: list[Message]) -> None:
        try:
            async with get_db_session(self._session_factory) as db:
                if await db.get(SessionRecord, session_id) is None:
                    return
                await db.execute(delete(MessageRecord).where(MessageRecord.session_id == session_id))
                for message in messages:
                    db.add(to_message_record(session_id, message))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_SAVE_MESSAGES_ERROR", str(exc)) from exc

    async def get_messages(self, session_id: str) -> list[Message]:
        try:
            async with get_db_session(self._session_factory) as db:
                statement = select(MessageRecord).where(MessageRecord.session_id == session_id).order_by(MessageRecord.timestamp, MessageRecord.id)
                records = (await db.execute(statement)).scalars().all()
                return [to_message(record) for record in records]
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_GET_MESSAGES_ERROR", str(exc)) from exc

    async def ensure_session(
        self,
        session_id: str,
        *,
        model: str = "",
        provider: str = "",
        system_prompt: str = "",
        max_tokens: int = 16384,
        title: str = "",
        workspace: str = "",
    ) -> None:
        """Create session record if not exists."""
        try:
            async with get_db_session(self._session_factory) as db:
                record = await db.get(SessionRecord, session_id)
                if record is not None:
                    if model:
                        record.model = model
                    if provider:
                        record.provider = provider
                    if system_prompt:
                        record.system_prompt = system_prompt
                    if title:
                        record.title = title
                    if workspace:
                        record.workspace = workspace
                    record.max_tokens = max_tokens
                    await db.commit()
                    return
                db.add(SessionRecord(
                    id=session_id,
                    title=title,
                    workspace=workspace,
                    model=model,
                    provider=provider,
                    system_prompt=system_prompt,
                    status="idle",
                    max_tokens=max_tokens,
                    created_at=datetime.utcnow(),
                ))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_ENSURE_ERROR", str(exc)) from exc

    async def add_messages(self, session_id: str, messages: list[Message]) -> None:
        """Append messages to an existing session without deleting old ones."""
        if not messages:
            return
        try:
            async with get_db_session(self._session_factory) as db:
                if await db.get(SessionRecord, session_id) is None:
                    return
                for message in messages:
                    db.add(to_message_record(session_id, message))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            raise AgentError("SESSION_STORE_ADD_MESSAGES_ERROR", str(exc)) from exc


__all__ = ["SessionStore"]
