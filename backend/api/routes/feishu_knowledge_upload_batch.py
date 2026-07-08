from __future__ import annotations

import asyncio
from time import time
from typing import Any

from pydantic import BaseModel, Field

from backend.api.routes.feishu_knowledge_tasks import run_knowledge_ingest_batch_payload
from backend.api.routes.feishu_knowledge_upload_batch_support import (
    batch_timeout,
    batch_ttl,
    clear_batch,
    count_key,
    files_key,
    first_key,
    last_key,
    lock_key,
    notify_batch_submitted,
    size_key,
)
from backend.common.logging import get_logger
from backend.common.utils.id_generator import generate_id
from backend.config import get_redis

logger = get_logger(component="feishu_knowledge_upload_batch")


class UploadBatchConfig(BaseModel):
    quiet_window_seconds: float = Field(default=5.0, ge=0.0)
    max_wait_seconds: float = Field(default=30.0, ge=1.0)
    max_files: int = Field(default=50, ge=1)
    max_total_bytes: int = Field(default=500 * 1024 * 1024, ge=1)


class FeishuFileItem(BaseModel):
    open_id: str
    chat_id: str
    message_id: str
    file_key: str
    file_name: str
    kb_id: str
    kb_name: str
    file_size: int = 0


DEFAULT_CONFIG = UploadBatchConfig()


async def add_file_to_upload_batch(
    context: Any,
    file: FeishuFileItem,
    config: UploadBatchConfig = DEFAULT_CONFIG,
) -> str:
    batch_key = build_upload_batch_key(file)
    redis = get_redis()
    if redis is None:
        await submit_ingest_batch(context, [file])
        return batch_key
    ttl = batch_ttl(config)
    now = time()
    await redis.set(first_key(batch_key), str(now), nx=True, ex=ttl)
    await redis.set(last_key(batch_key), str(now), ex=ttl)
    await redis.rpush(files_key(batch_key), file.model_dump_json())
    await redis.expire(files_key(batch_key), ttl)
    count = int(await redis.incr(count_key(batch_key)))
    total_size = int(await redis.incrby(size_key(batch_key), max(file.file_size, 0)))
    await redis.expire(count_key(batch_key), ttl)
    await redis.expire(size_key(batch_key), ttl)
    asyncio.create_task(_delayed_flush(batch_key, context, config))
    if count >= config.max_files or total_size >= config.max_total_bytes:
        await flush_upload_batch(batch_key, context, config)
    return batch_key


async def flush_upload_batch(
    batch_key: str,
    context: Any,
    config: UploadBatchConfig = DEFAULT_CONFIG,
) -> None:
    redis = get_redis()
    if redis is None:
        return
    locked = await redis.set(lock_key(batch_key), "1", nx=True, ex=60)
    if not locked:
        return
    try:
        raw_files = await redis.lrange(files_key(batch_key), 0, -1)
        files = [
            FeishuFileItem.model_validate_json(str(raw))
            for raw in raw_files
            if str(raw).strip()
        ]
        try:
            await submit_ingest_batch(context, files)
        except Exception as exc:  # noqa: BLE001
            # 提交失败：批次保留在 Redis（不 clear），重新 arm 一次延迟 flush 以便重投，
            # 避免仅靠 TTL 过期而静默丢文件。
            logger.error("upload_batch_submit_failed", batch_key=batch_key, error=str(exc))
            asyncio.create_task(_delayed_flush(batch_key, context, config))
            return
        await clear_batch(redis, batch_key)
    finally:
        await redis.delete(lock_key(batch_key))


async def submit_ingest_batch(context: Any, files: list[FeishuFileItem]) -> None:
    if not files:
        return
    payload = {
        "kind": "knowledge_ingest_batch",
        "chat_id": files[0].chat_id,
        "kb_id": files[0].kb_id,
        "kb_name": files[0].kb_name,
        "task_id": generate_id(),
        "files": [file.model_dump() for file in files],
    }
    queue = context.handler._task_queue  # noqa: SLF001
    if queue is not None:
        await queue.submit(payload["task_id"], payload, batch_timeout(files), 0)
    else:
        asyncio.create_task(run_knowledge_ingest_batch_payload(payload))
    # queue.submit 是唯一决定入库成败的步骤；提交成功后清 pending 与提示均容错。
    await notify_batch_submitted(context, files)


def build_upload_batch_key(file: FeishuFileItem) -> str:
    return f"feishu:kb_upload:{file.open_id}:{file.chat_id}:{file.kb_id}"


async def _delayed_flush(
    batch_key: str,
    context: Any,
    config: UploadBatchConfig,
) -> None:
    await asyncio.sleep(config.quiet_window_seconds)
    if await _should_flush(batch_key, config):
        await flush_upload_batch(batch_key, context, config)


async def _should_flush(batch_key: str, config: UploadBatchConfig) -> bool:
    redis = get_redis()
    if redis is None:
        return False
    first = await redis.get(first_key(batch_key))
    last = await redis.get(last_key(batch_key))
    if first is None or last is None:
        return False
    now = time()
    first_seen = float(first)
    last_seen = float(last)
    return (
        now - last_seen >= config.quiet_window_seconds
        or now - first_seen >= config.max_wait_seconds
    )


__all__ = [
    "DEFAULT_CONFIG",
    "FeishuFileItem",
    "UploadBatchConfig",
    "add_file_to_upload_batch",
    "build_upload_batch_key",
    "flush_upload_batch",
    "submit_ingest_batch",
]
