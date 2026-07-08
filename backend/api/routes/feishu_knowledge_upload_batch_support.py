from __future__ import annotations

from typing import Any

from backend.common.logging import get_logger

logger = get_logger(component="feishu_knowledge_upload_batch")


async def notify_batch_submitted(context: Any, files: list[Any]) -> None:
    # 入库已提交后的收尾：清 pending 与用户提示均容错，失败不得回滚已成功的入库。
    first = files[0]
    try:
        await context.handler._menu_state.clear_pending(first.open_id)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "upload_batch_clear_pending_failed", open_id=first.open_id, error=str(exc)
        )
    try:
        await context.handler._send_chat_text(  # noqa: SLF001
            first.chat_id,
            f"收到 {len(files)} 个文件，正在入库到「{first.kb_name}」",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "upload_batch_notify_failed", chat_id=first.chat_id, error=str(exc)
        )


async def clear_batch(redis: Any, batch_key: str) -> None:
    await redis.delete(
        files_key(batch_key),
        first_key(batch_key),
        last_key(batch_key),
        count_key(batch_key),
        size_key(batch_key),
    )


def batch_timeout(files: list[Any]) -> int:
    return max(900, min(12 * 3600, 900 * len(files)))


def batch_ttl(config: Any) -> int:
    return int(config.max_wait_seconds + config.quiet_window_seconds + 120)


def files_key(batch_key: str) -> str:
    return f"{batch_key}:files"


def first_key(batch_key: str) -> str:
    return f"{batch_key}:first_seen"


def last_key(batch_key: str) -> str:
    return f"{batch_key}:last_seen"


def count_key(batch_key: str) -> str:
    return f"{batch_key}:count"


def size_key(batch_key: str) -> str:
    return f"{batch_key}:total_size"


def lock_key(batch_key: str) -> str:
    return f"{batch_key}:lock"


__all__ = [
    "batch_timeout",
    "batch_ttl",
    "clear_batch",
    "count_key",
    "files_key",
    "first_key",
    "last_key",
    "lock_key",
    "notify_batch_submitted",
    "size_key",
]
