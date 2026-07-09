from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.common.types import Message, Session, SessionConfig
from backend.storage.database import get_db_session
from backend.storage.models import MessageRecord, SessionRecord
from backend.storage.session_store import SessionStore

from .storage_test_support import make_test_session_factory


def _session(session_id: str, created_at: datetime, message_count: int) -> Session:
    messages = [
        Message(role="user", content=f"{session_id}-msg-{index}")
        for index in range(message_count)
    ]
    return Session(
        id=session_id,
        config=SessionConfig(model="glm-4-plus", provider="glm"),
        messages=messages,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_list_all_aggregates_counts_and_excludes_sub_agent(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "sessions_list_aggregate")
    store = SessionStore(factory)
    now = datetime.utcnow()

    try:
        await store.create(_session("session-a", now - timedelta(minutes=2), 2), title="A")
        await store.create(_session("session-b", now - timedelta(minutes=1), 3), title="B")
        # sub-agent checkpoint 会话（最新），应被 list_all 排除
        await store.create(_session("sub-agent:task-1", now, 4), title="checkpoint")

        listed = await store.list_all()

        # 仅普通会话，按 created_at 倒序；sub-agent 会话被排除
        assert [session.id for session, _count in listed] == ["session-b", "session-a"]
        # 消息条数为聚合计数，且正确
        assert {session.id: count for session, count in listed} == {
            "session-b": 3,
            "session-a": 2,
        }
        # 未做全量 message 反序列化：返回的轻量 Session 不携带 messages 列表
        assert all(session.messages == [] for session, _count in listed)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_purge_sub_agent_sessions_removes_old_and_cascades_messages(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "sessions_purge_sub_agent")
    store = SessionStore(factory)
    now = datetime.utcnow()
    old = now - timedelta(days=10)

    try:
        await store.create(_session("sub-agent:old", old, 3), title="old checkpoint")
        await store.create(_session("sub-agent:fresh", now, 2), title="fresh checkpoint")
        # 普通会话即便同样"旧"，也不受 sub-agent 回收影响
        await store.create(_session("session-keep", old, 1), title="normal old")

        removed = await store.purge_sub_agent_sessions(before=now - timedelta(days=1))

        assert removed == 1  # 仅回收 1 个过期 sub-agent 会话

        async with get_db_session(factory) as db:
            remaining_ids = set(
                (await db.execute(select(SessionRecord.id))).scalars().all()
            )
            # 旧 sub-agent 被删；新 sub-agent 与普通会话保留
            assert remaining_ids == {"sub-agent:fresh", "session-keep"}
            # 级联删消息：旧 sub-agent 的 3 条消息随会话一并删除
            old_msg_count = await db.scalar(
                select(func.count())
                .select_from(MessageRecord)
                .where(MessageRecord.session_id == "sub-agent:old")
            )
            assert old_msg_count == 0
            # 其余会话消息不受影响：fresh(2) + keep(1)
            total_msg_count = await db.scalar(
                select(func.count()).select_from(MessageRecord)
            )
            assert total_msg_count == 3
    finally:
        await engine.dispose()
