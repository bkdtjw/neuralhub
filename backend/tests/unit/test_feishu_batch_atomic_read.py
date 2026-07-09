from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from backend.api.routes import feishu_knowledge_upload_batch as batch_mod
from backend.api.routes.feishu_knowledge_flow import KbContext
from backend.api.routes.feishu_knowledge_upload_batch import (
    FeishuFileItem,
    UploadBatchConfig,
    build_upload_batch_key,
    flush_upload_batch,
)
from backend.api.routes.feishu_knowledge_upload_batch_support import files_key
from backend.api.routes.feishu_menu_state import FeishuMenuState
from backend.config import get_redis


@pytest_asyncio.fixture(autouse=True)
async def bind_test_database() -> AsyncIterator[None]:
    # 覆盖 conftest 的 DB 绑定：本模块纯内存（fakeredis）单测，跳过 PostgresContainer。
    yield


pytestmark = pytest.mark.asyncio

# quiet/max_wait 拉大：失败路径重新 arm 的 _delayed_flush 不会在测试窗口内触发。
CONFIG = UploadBatchConfig(quiet_window_seconds=30, max_wait_seconds=60)


class _QueueProbe:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def submit(
        self, task_id: str, payload: dict[str, Any], timeout_seconds: int, max_retries: int
    ) -> None:
        self.payloads.append(payload)


class _Handler:
    def __init__(self) -> None:
        self._menu_state = FeishuMenuState()
        self._task_queue = _QueueProbe()
        self.sent: list[tuple[str, str]] = []

    async def _send_chat_text(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def _file(message_id: str, name: str) -> FeishuFileItem:
    return FeishuFileItem(
        open_id="ou_atomic",
        chat_id="oc_atomic",
        message_id=message_id,
        file_key=f"key_{message_id}",
        file_name=name,
        kb_id="kb_dsp",
        kb_name="数字信号处理",
        file_size=1024,
    )


def _context(handler: _Handler) -> KbContext:
    return KbContext(handler, "ou_atomic", "oc_atomic", "om_atomic")


async def _seed(batch_key: str, *files: FeishuFileItem) -> None:
    redis = get_redis()
    for file in files:
        await redis.rpush(files_key(batch_key), file.model_dump_json())


async def _names_in_redis(batch_key: str) -> list[str]:
    raw = await get_redis().lrange(files_key(batch_key), 0, -1)
    return [FeishuFileItem.model_validate_json(item).file_name for item in raw]


async def test_flush_preserves_window_file_arriving_during_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 复现 E7：flush 读取批次后、清空批次前，并发 rpush 到达的窗口期文件不得被静默丢弃。
    handler = _Handler()
    f1, f2, window = _file("om_1", "a.pdf"), _file("om_2", "b.pdf"), _file("om_3", "c.pdf")
    batch_key = build_upload_batch_key(f1)
    await _seed(batch_key, f1, f2)

    submitted: list[list[str]] = []
    real_submit = batch_mod.submit_ingest_batch

    async def _spy(context: Any, files: list[FeishuFileItem]) -> None:
        # 模拟“读取批次”与“清空批次”之间到达的一个窗口期文件（rpush 追加到表尾）。
        await get_redis().rpush(files_key(batch_key), window.model_dump_json())
        submitted.append([file.file_name for file in files])
        await real_submit(context, files)

    monkeypatch.setattr(batch_mod, "submit_ingest_batch", _spy)

    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    # 读出并提交的是 a/b；窗口期到达的 c 仍在 Redis，未被整键 DEL 清掉。
    assert submitted == [["a.pdf", "b.pdf"]]
    remaining = await _names_in_redis(batch_key)
    assert remaining == ["c.pdf"]
    # 读出的 files ∪ 之后仍在 Redis 的 files == 全部 rpush 的文件，无静默丢弃。
    assert set(submitted[0]) | set(remaining) == {"a.pdf", "b.pdf", "c.pdf"}


async def test_flush_preserves_multiple_window_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 窗口期到达多个文件（均追加到表尾）时，LTRIM 只删已提交的前 N 个，全部窗口期文件保留。
    handler = _Handler()
    f1, f2 = _file("om_1", "a.pdf"), _file("om_2", "b.pdf")
    win1, win2 = _file("om_3", "c.pdf"), _file("om_4", "d.pdf")
    batch_key = build_upload_batch_key(f1)
    await _seed(batch_key, f1, f2)
    real_submit = batch_mod.submit_ingest_batch

    async def _spy(context: Any, files: list[FeishuFileItem]) -> None:
        redis = get_redis()
        await redis.rpush(files_key(batch_key), win1.model_dump_json())
        await redis.rpush(files_key(batch_key), win2.model_dump_json())
        await real_submit(context, files)

    monkeypatch.setattr(batch_mod, "submit_ingest_batch", _spy)
    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert await _names_in_redis(batch_key) == ["c.pdf", "d.pdf"]
    assert len(handler._task_queue.payloads) == 1


async def test_flush_failure_keeps_read_and_window_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 提交失败：批次整体保留（不 trim/不 clear），已读文件与窗口期文件都留在 Redis 等重投。
    handler = _Handler()
    f1, f2, window = _file("om_1", "a.pdf"), _file("om_2", "b.pdf"), _file("om_3", "c.pdf")
    batch_key = build_upload_batch_key(f1)
    await _seed(batch_key, f1, f2)

    async def _boom(context: Any, files: list[FeishuFileItem]) -> None:
        await get_redis().rpush(files_key(batch_key), window.model_dump_json())
        raise RuntimeError("submit exploded")

    monkeypatch.setattr(batch_mod, "submit_ingest_batch", _boom)
    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert await _names_in_redis(batch_key) == ["a.pdf", "b.pdf", "c.pdf"]


async def test_flush_clears_entire_batch_without_window_file() -> None:
    # 无窗口期文件时，LTRIM 精确移除已提交项后 files_key 清空（不残留、键被删除）。
    handler = _Handler()
    f1, f2 = _file("om_1", "a.pdf"), _file("om_2", "b.pdf")
    batch_key = build_upload_batch_key(f1)
    await _seed(batch_key, f1, f2)

    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert await _names_in_redis(batch_key) == []
    assert await get_redis().exists(files_key(batch_key)) == 0
    assert len(handler._task_queue.payloads) == 1
