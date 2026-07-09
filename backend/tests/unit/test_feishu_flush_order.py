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
    submit_ingest_batch,
)
from backend.api.routes.feishu_knowledge_upload_batch_support import files_key, lock_key
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
    def __init__(self, submit_error: Exception | None = None) -> None:
        self.submit_error = submit_error
        self.payloads: list[dict[str, Any]] = []

    async def submit(
        self, task_id: str, payload: dict[str, Any], timeout_seconds: int, max_retries: int
    ) -> None:
        if self.submit_error is not None:
            raise self.submit_error
        self.payloads.append(payload)


class _Handler:
    def __init__(
        self,
        *,
        submit_error: Exception | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self._menu_state = FeishuMenuState()
        self._task_queue = _QueueProbe(submit_error)
        self._send_error = send_error
        self.sent: list[tuple[str, str]] = []

    async def _send_chat_text(self, chat_id: str, text: str) -> None:
        if self._send_error is not None:
            raise self._send_error
        self.sent.append((chat_id, text))


def _file(message_id: str, name: str) -> FeishuFileItem:
    return FeishuFileItem(
        open_id="ou_flush",
        chat_id="oc_flush",
        message_id=message_id,
        file_key=f"key_{message_id}",
        file_name=name,
        kb_id="kb_dsp",
        kb_name="数字信号处理",
        file_size=1024,
    )


def _context(handler: _Handler) -> KbContext:
    return KbContext(handler, "ou_flush", "oc_flush", "om_flush")


async def _seed_two_files() -> str:
    batch_key = build_upload_batch_key(_file("om_1", "a.pdf"))
    redis = get_redis()
    await redis.rpush(files_key(batch_key), _file("om_1", "a.pdf").model_dump_json())
    await redis.rpush(files_key(batch_key), _file("om_2", "b.pdf").model_dump_json())
    return batch_key


async def _remaining(batch_key: str) -> list[str]:
    return await get_redis().lrange(files_key(batch_key), 0, -1)


async def test_flush_keeps_batch_when_submit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _Handler()
    batch_key = await _seed_two_files()

    async def _boom(_context: Any, _files: list[FeishuFileItem]) -> None:
        raise RuntimeError("submit exploded")

    monkeypatch.setattr(batch_mod, "submit_ingest_batch", _boom)

    # flush 不应抛出：吞掉异常、记录 error、保留批次并重新 arm 重投。
    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert len(await _remaining(batch_key)) == 2  # 批次仍在 Redis，未被 clear
    assert await get_redis().get(lock_key(batch_key)) is None  # 锁已释放，可再次 flush


async def test_flush_keeps_batch_when_queue_submit_raises() -> None:
    # queue.submit 失败 -> 真实 submit_ingest_batch 向上抛 -> flush 捕获并保留批次。
    handler = _Handler(submit_error=RuntimeError("queue down"))
    batch_key = await _seed_two_files()

    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert len(await _remaining(batch_key)) == 2
    assert handler._task_queue.payloads == []  # 未成功入队


async def test_flush_clears_even_if_notify_raises() -> None:
    # _send_chat_text 抛异常不得影响 submit 成败判定：入队成功 -> 批次照常清空。
    handler = _Handler(send_error=RuntimeError("feishu api 500"))
    batch_key = await _seed_two_files()

    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert await _remaining(batch_key) == []  # 提交成功 -> 批次已清
    assert len(handler._task_queue.payloads) == 1  # 入队成功
    assert handler.sent == []  # 提示抛异常被吞


async def test_flush_submits_before_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _Handler()
    batch_key = await _seed_two_files()
    real_submit = batch_mod.submit_ingest_batch
    seen: dict[str, int] = {}

    async def _spy(context: Any, files: list[FeishuFileItem]) -> None:
        # submit 执行时批次必须仍在 Redis（clear 只能发生在 submit 成功之后）。
        seen["at_submit"] = len(await _remaining(batch_key))
        await real_submit(context, files)

    monkeypatch.setattr(batch_mod, "submit_ingest_batch", _spy)

    await flush_upload_batch(batch_key, _context(handler), CONFIG)

    assert seen["at_submit"] == 2  # 先 submit：此时批次未清
    assert await _remaining(batch_key) == []  # 后 clear：submit 成功后清空
    assert len(handler._task_queue.payloads) == 1
    assert handler.sent == [("oc_flush", "收到 2 个文件，正在入库到「数字信号处理」")]


async def test_submit_ingest_batch_propagates_queue_failure() -> None:
    # queue.submit 是唯一决定成败的步骤：其失败必须向上抛。
    handler = _Handler(submit_error=RuntimeError("queue down"))
    with pytest.raises(RuntimeError, match="queue down"):
        await submit_ingest_batch(_context(handler), [_file("om_1", "a.pdf")])
    assert handler.sent == []  # 提示在 submit 之后，不会发出


async def test_submit_ingest_batch_tolerates_notify_failure() -> None:
    handler = _Handler(send_error=RuntimeError("feishu api 500"))
    await submit_ingest_batch(_context(handler), [_file("om_1", "a.pdf")])  # 不抛
    assert len(handler._task_queue.payloads) == 1
    assert handler.sent == []
