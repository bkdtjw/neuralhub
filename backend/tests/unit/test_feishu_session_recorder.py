from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.api.routes.feishu_session_recorder import (
    FeishuOutboundFileRecord,
    FeishuOutboundTextRecord,
    FeishuRecordConfig,
    FeishuSessionRecorder,
)
from backend.storage.memory_store import MemoryStore
from backend.storage.session_store import SessionStore

from .storage_test_support import make_test_session_factory


@pytest.mark.asyncio
async def test_recorder_persists_outbound_text_context(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "feishu_recorder_text")
    store = SessionStore(factory)
    recorder = FeishuSessionRecorder(store, MemoryStore(str(tmp_path / "memory.json")))

    try:
        await recorder.record_text(
            FeishuOutboundTextRecord(
                chat_id="oc_1",
                text="已提取字幕并发送附件",
                config=FeishuRecordConfig(model="m", provider="p", system_prompt="sys"),
            )
        )

        session = await store.get("oc_1")
        assert session is not None
        assert session.config.system_prompt == "sys"
        messages = await store.get_messages("oc_1")
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].kind == "runtime_context"
        assert "已提取字幕并发送附件" in messages[0].content
        assert messages[0].provider_metadata["feishu"]["message_type"] == "text"
        assert messages[0].provider_metadata["feishu"]["body_status"] == "inline"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recorder_does_not_persist_file_memory_by_default(tmp_path) -> None:
    memory_store = MemoryStore(str(tmp_path / "memory.json"))
    store = AsyncMock()
    store.ensure_session = AsyncMock()
    store.add_messages = AsyncMock()
    recorder = FeishuSessionRecorder(store, memory_store)

    await recorder.record_file(
        FeishuOutboundFileRecord(
            chat_id="oc_1",
            file_name="BqF6PUAXY1M.zh-Hans.cleaned.txt",
            summary="立党 AI 学习教程字幕",
        )
    )

    assert memory_store.load().entries == []


@pytest.mark.asyncio
async def test_recorder_persists_file_context_and_memory(tmp_path) -> None:
    engine, factory = await make_test_session_factory(tmp_path, "feishu_recorder_file")
    memory_store = MemoryStore(str(tmp_path / "memory.json"))
    store = SessionStore(factory)
    recorder = FeishuSessionRecorder(store, memory_store)

    try:
        await recorder.record_file(
            FeishuOutboundFileRecord(
                chat_id="oc_1",
                file_name="BqF6PUAXY1M.zh-Hans.cleaned.txt",
                file_key="file-key",
                local_path="/tmp/subtitle.txt",
                summary="立党 AI 学习教程字幕",
                persist_memory=True,
            )
        )

        messages = await store.get_messages("oc_1")
        assert "BqF6PUAXY1M.zh-Hans.cleaned.txt" in messages[0].content
        assert "不代表模型已读取附件全文" in messages[0].content
        assert messages[0].provider_metadata["feishu"]["file_key"] == "file-key"
        assert messages[0].provider_metadata["feishu"]["body_status"] == "metadata_only"
        memory = memory_store.load()
        assert len(memory.entries) == 1
        assert memory.entries[0].source_session == "oc_1"
        assert "字幕" in memory.entries[0].keywords
    finally:
        await engine.dispose()
