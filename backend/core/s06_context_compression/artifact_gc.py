from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

from backend.common.logging import get_logger

logger = get_logger(component="artifact_gc")

RETENTION_DAYS = 7
# data/sessions 是 L3 唯一无损备份，保留期远长于 artifacts，避免误删仍被引用的备份。
SESSION_RETENTION_DAYS = 90
# sub-agent:{task_id} checkpoint 会话随每个子任务累积、永不清理，按短保留期回收。
SUB_AGENT_SESSION_RETENTION_DAYS = 7
GC_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_ROOTS = ("data/artifacts",)
SESSION_ROOT = "data/sessions"


def cleanup_expired_artifacts(
    days: int = RETENTION_DAYS,
    session_days: int = SESSION_RETENTION_DAYS,
) -> int:
    now = time.time()
    removed = 0
    artifact_cutoff = now - days * 24 * 60 * 60
    for root in DEFAULT_ROOTS:
        removed += _cleanup_root(Path(root), artifact_cutoff)
    # data/sessions 单独用远长的保留期清理，避免把仍被引用的 L3 备份 7 天误删。
    removed += _cleanup_root(Path(SESSION_ROOT), now - session_days * 24 * 60 * 60)
    return removed


async def purge_expired_sub_agent_sessions(
    days: int = SUB_AGENT_SESSION_RETENTION_DAYS,
) -> int:
    # 惰性导入 SessionStore，避免 core→storage 在模块加载期形成环。
    from backend.storage import SessionStore

    cutoff = datetime.utcnow() - timedelta(days=days)
    return await SessionStore().purge_sub_agent_sessions(cutoff)


async def run_artifact_gc_loop(shutdown_event: asyncio.Event) -> None:
    try:
        while not shutdown_event.is_set():
            try:
                cleanup_expired_artifacts()
            except Exception:  # noqa: BLE001
                # 单轮任意异常都不能杀死循环：记录后进入下一轮 sleep，保持 GC 常驻。
                logger.exception("artifact_gc_cleanup_failed")
            try:
                await purge_expired_sub_agent_sessions()
            except Exception:  # noqa: BLE001
                # DB 回收失败（如库暂时不可达）同样不能杀死循环。
                logger.exception("artifact_gc_sub_agent_purge_failed")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=GC_INTERVAL_SECONDS)
            except TimeoutError:
                continue
    except asyncio.CancelledError:
        return


def _cleanup_root(root: Path, cutoff: float) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            if path.is_dir():
                _remove_empty_dir(path)
            elif path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            # 坏文件（权限/竞态删除等）跳过，继续清理其它过期文件。
            continue
    return removed


def _remove_empty_dir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        return
