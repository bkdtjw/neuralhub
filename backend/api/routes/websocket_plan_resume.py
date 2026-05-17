from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.s01_agent_loop import PlanCheckpointStore, PlanExecuteRunner, PlanStore, TodoStore
from backend.core.s05_skills import AgentRuntime, SpecRegistry
from backend.core.task_queue import TaskQueue
from backend.storage import SessionStore

from .websocket_plan import WsPlanRenderer, create_plan_runner
from .websocket_runtime import RuntimeComponentsInput, create_runtime_components
from .websocket_support import LoopSettings


async def create_plan_resume_runner(
    settings: LoopSettings,
    session_id: str,
    send_message: Callable[[dict[str, Any]], Awaitable[None]],
    store: SessionStore | None,
    agent_runtime: AgentRuntime | None,
    spec_registry: SpecRegistry | None,
    task_queue: TaskQueue | None,
    checkpoint_store: PlanCheckpointStore,
) -> PlanExecuteRunner | None:
    renderer = WsPlanRenderer(send_message)
    if settings.spec_id:
        base = await create_plan_runner(
            settings, session_id, send_message, store, agent_runtime, spec_registry, task_queue
        )
        resumed = PlanExecuteRunner.resume_from_checkpoint(
            checkpoint_store,
            session_id,
            base._adapter,
            base._tool_registry,
            base._plan_store,
            base._todo_store,
            renderer,
            owner_id=session_id,
        )
        if resumed is None:
            return None
        base._state = resumed._state
        base._checkpoint_path = resumed._checkpoint_path
        base._plan_path = resumed._plan_path
        base._todo_path = resumed._todo_path
        return base
    components = await create_runtime_components(
        RuntimeComponentsInput(
            settings=settings,
            agent_runtime=agent_runtime,
            spec_registry=spec_registry,
            task_queue=task_queue,
            event_sender=send_message,
        )
    )
    runner = PlanExecuteRunner.resume_from_checkpoint(
        checkpoint_store,
        session_id,
        components.adapter,
        components.registry,
        PlanStore(),
        TodoStore(),
        renderer,
        bridge=components.bridge,
        owner_id=session_id,
    )
    return runner


__all__ = ["create_plan_resume_runner"]
