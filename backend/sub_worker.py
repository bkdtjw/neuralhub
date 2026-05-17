from __future__ import annotations

import asyncio
import signal

from backend.adapters.provider_manager import ProviderManager
from backend.common.errors import AgentError
from backend.common.logging import get_logger, setup_logging
from backend.common.metrics import close_metrics, init_metrics
from backend.config import close_redis, get_redis, init_redis, settings
from backend.core import create_sub_agent_task_queue, init_agent_runtime
from backend.core.s06_context_compression.artifact_gc import run_artifact_gc_loop
from backend.core.s02_tools.mcp import MCPServerManager
from backend.core.task_queue import TaskQueue
from backend.api.task_queue_consumer import SubAgentConsumerContext, consume_next_sub_agent_task
from backend.storage import SubAgentTaskStore, init_db

logger = get_logger(component="sub_worker")
TASK_QUEUE_RECOVERY_INTERVAL_SECONDS = 30


async def main() -> None:
    provider_manager = ProviderManager()
    mcp_manager = MCPServerManager()
    shutdown_event = asyncio.Event()
    background_tasks: list[asyncio.Task[None]] = []
    try:
        await init_db()
        await init_redis()
        await init_metrics()
        _, agent_runtime = await init_agent_runtime(provider_manager, mcp_manager, settings)
        redis = get_redis()
        if redis is None:
            raise AgentError("TASK_QUEUE_REDIS_MISSING", "Redis client is not initialized.")
        queue = create_sub_agent_task_queue(redis, persistence=SubAgentTaskStore())
        _install_signal_handlers(shutdown_event)
        background_tasks = _create_background_tasks(
            SubAgentConsumerContext(queue=queue, runtime=agent_runtime),
            shutdown_event,
        )
        logger.info(
            "sub_worker_started",
            concurrency=_consumer_concurrency(),
            namespace=queue.namespace,
        )
        await shutdown_event.wait()
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SUB_WORKER_RUNTIME_ERROR", str(exc)) from exc
    finally:
        await _shutdown(background_tasks, shutdown_event, mcp_manager)


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)


def _create_background_tasks(
    context: SubAgentConsumerContext,
    shutdown_event: asyncio.Event,
) -> list[asyncio.Task[None]]:
    tasks = [
        asyncio.create_task(
            _consume_loop(context, shutdown_event),
            name=f"sub-worker-consumer-{index}",
        )
        for index in range(1, _consumer_concurrency() + 1)
    ]
    tasks.append(
        asyncio.create_task(
            _recover_loop(context.queue, shutdown_event),
            name="sub-worker-recovery",
        )
    )
    tasks.append(
        asyncio.create_task(run_artifact_gc_loop(shutdown_event), name="artifact-gc")
    )
    return tasks


def _consumer_concurrency() -> int:
    if settings.sub_worker_concurrency < 1:
        raise AgentError("SUB_WORKER_CONCURRENCY_INVALID", "SUB_WORKER_CONCURRENCY must be >= 1.")
    return settings.sub_worker_concurrency


async def _consume_loop(
    context: SubAgentConsumerContext,
    shutdown_event: asyncio.Event,
) -> None:
    logger.info("task_queue_consumer_started", namespace=context.queue.namespace)
    while not shutdown_event.is_set():
        try:
            processed = await consume_next_sub_agent_task(context)
            if not processed:
                await _wait_for_shutdown(shutdown_event, 1.0)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "consumer_loop_error",
                namespace=context.queue.namespace,
                error=str(exc),
            )
            await _wait_for_shutdown(shutdown_event, 1.0)


async def _recover_loop(queue: TaskQueue, shutdown_event: asyncio.Event) -> None:
    logger.info(
        "task_queue_recovery_started",
        namespace=queue.namespace,
        interval_seconds=TASK_QUEUE_RECOVERY_INTERVAL_SECONDS,
    )
    while not shutdown_event.is_set():
        try:
            recovered = await queue.recover_stale_tasks()
            if recovered:
                logger.info(
                    "task_queue_recovery_completed",
                    namespace=queue.namespace,
                    recovered=recovered,
                )
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("task_queue_recovery_error", namespace=queue.namespace)
        await _wait_for_shutdown(shutdown_event, TASK_QUEUE_RECOVERY_INTERVAL_SECONDS)


async def _wait_for_shutdown(shutdown_event: asyncio.Event, delay_seconds: float) -> None:
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=delay_seconds)
    except TimeoutError:
        return
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SUB_WORKER_WAIT_ERROR", str(exc)) from exc


async def _shutdown(
    background_tasks: list[asyncio.Task[None]],
    shutdown_event: asyncio.Event,
    mcp_manager: MCPServerManager,
) -> None:
    try:
        shutdown_event.set()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        close_metrics()
        await close_redis()
        await mcp_manager.disconnect_all()
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("SUB_WORKER_SHUTDOWN_ERROR", str(exc)) from exc


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
