from __future__ import annotations

import asyncio

from fastapi import FastAPI
from sqlalchemy import text

from backend.common.errors import AgentError
from backend.common.logging import get_logger, get_worker_id
from backend.config import get_redis
from backend.core import create_sub_agent_task_queue
from backend.core.s06_context_compression.artifact_gc import run_artifact_gc_loop
from backend.core.task_queue import TaskQueue
from backend.storage import SubAgentTaskStore
from backend.storage.database import engine

logger = get_logger(component="lifespan_support")


def init_task_queue(app: FastAPI) -> TaskQueue:
    try:
        redis = get_redis()
        if redis is None:
            raise AgentError("TASK_QUEUE_REDIS_MISSING", "Redis client is not initialized.")
        queue = create_sub_agent_task_queue(redis, persistence=SubAgentTaskStore())
        app.state.task_queue = queue
        app.state.worker_id = get_worker_id()
        return queue
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("TASK_QUEUE_INIT_ERROR", str(exc)) from exc


async def check_readiness() -> dict[str, bool]:
    postgres_ready = False
    redis_ready = False
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        postgres_ready = True
    except Exception:
        postgres_ready = False
    try:
        redis = get_redis()
        if redis is not None:
            await redis.ping()
            redis_ready = True
    except Exception:
        redis_ready = False
    return {"postgres": postgres_ready, "redis": redis_ready}


def start_artifact_gc(app: FastAPI) -> None:
    # 幂等：已有任务则不重复启动（避免 lifespan 复用时并发多个 GC 循环）。
    if getattr(app.state, "artifact_gc_task", None) is not None:
        return
    try:
        shutdown_event = asyncio.Event()
        app.state.artifact_gc_shutdown = shutdown_event
        app.state.artifact_gc_task = asyncio.create_task(
            run_artifact_gc_loop(shutdown_event), name="artifact-gc"
        )
    except Exception:  # noqa: BLE001
        # GC 是尽力而为的后台清理，启动失败不应拖垮 API 生命周期。
        logger.exception("artifact_gc_start_failed")


async def stop_artifact_gc(app: FastAPI) -> None:
    task = getattr(app.state, "artifact_gc_task", None)
    shutdown_event = getattr(app.state, "artifact_gc_shutdown", None)
    if task is None:
        return
    try:
        if shutdown_event is not None:
            shutdown_event.set()
        await asyncio.gather(task, return_exceptions=True)
    except Exception:  # noqa: BLE001
        logger.exception("artifact_gc_stop_failed")
    finally:
        app.state.artifact_gc_task = None
        app.state.artifact_gc_shutdown = None


__all__ = [
    "check_readiness",
    "init_task_queue",
    "start_artifact_gc",
    "stop_artifact_gc",
]
