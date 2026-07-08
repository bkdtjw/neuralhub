from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

from backend.common.types import Message, Session, SessionConfig, ToolCall, ToolResult
from backend.storage.database import get_db_session
from backend.storage.models import MessageRecord, SessionRecord
from backend.storage.session_store import SessionStore

from .storage_test_support import make_test_session_factory


@pytest.mark.asyncio
async def test_session_store_crud_roundtrip(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "session_store")
    store = SessionStore(factory)
    session = Session(config=SessionConfig(model="glm-4-plus", provider="glm"), created_at=datetime.utcnow())

    try:
        created = await store.create(session, title="initial", workspace="C:/demo")
        fetched = await store.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "initial"
        assert fetched.workspace == "C:/demo"
        assert fetched.config.model == "glm-4-plus"

        listed = await store.list_all()
        assert [session.id for session, _count in listed] == [created.id]
        assert [count for _session, count in listed] == [0]

        updated = await store.update_title(created.id, "updated")
        assert updated is not None
        async with get_db_session(factory) as db:
            record = await db.get(SessionRecord, created.id)
            assert record is not None
            assert record.title == "updated"
            assert record.workspace == "C:/demo"

        messages = [
            Message(role="user", content="list files"),
            Message(
                role="assistant",
                content="checking",
                tool_calls=[ToolCall(id="tool_1", name="Bash", arguments={"command": "dir"})],
                tool_results=[ToolResult(tool_call_id="tool_1", output="file list", is_error=False)],
                provider_metadata={"reasoning_content": "thinking"},
            ),
        ]
        await store.save_messages(created.id, messages)
        saved_messages = await store.get_messages(created.id)
        assert [item.content for item in saved_messages] == ["list files", "checking"]
        assert saved_messages[1].tool_calls is not None
        assert saved_messages[1].tool_calls[0].arguments["command"] == "dir"
        assert saved_messages[1].tool_results is not None
        assert saved_messages[1].tool_results[0].output == "file list"
        assert saved_messages[1].provider_metadata["reasoning_content"] == "thinking"

        assert await store.delete(created.id) is True
        assert await store.get(created.id) is None
        assert await store.get_messages(created.id) == []
        assert await store.list_all() == []

        async with get_db_session(factory) as db:
            session_count = await db.scalar(select(func.count()).select_from(SessionRecord))
            message_count = await db.scalar(select(func.count()).select_from(MessageRecord))
            assert session_count == 0
            assert message_count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_session_persists_explicit_max_tokens(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "session_store_ensure")
    store = SessionStore(factory)

    try:
        await store.ensure_session(
            "session-explicit-max-tokens",
            model="kimi-k2.6",
            provider="kimi",
            system_prompt="system",
            max_tokens=16384,
            title="scheduled session",
            workspace="scheduled_task",
        )
        async with get_db_session(factory) as db:
            record = await db.get(SessionRecord, "session-explicit-max-tokens")
            assert record is not None
            assert record.max_tokens == 16384
            assert record.title == "scheduled session"
            assert record.workspace == "scheduled_task"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_session_updates_existing_session_config(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "session_store_update")
    store = SessionStore(factory)

    try:
        await store.ensure_session(
            "session-update",
            model="old-model",
            provider="old-provider",
            system_prompt="old-system",
            max_tokens=4096,
            title="old title",
            workspace="old_workspace",
        )
        await store.ensure_session(
            "session-update",
            model="glm-5.1",
            provider="provider-1",
            system_prompt="new-system",
            max_tokens=16384,
            title="new title",
            workspace="new_workspace",
        )
        async with get_db_session(factory) as db:
            record = await db.get(SessionRecord, "session-update")
            assert record is not None
            assert record.model == "glm-5.1"
            assert record.provider == "provider-1"
            assert record.system_prompt == "new-system"
            assert record.max_tokens == 16384
            assert record.title == "new title"
            assert record.workspace == "new_workspace"
    finally:
        await engine.dispose()
