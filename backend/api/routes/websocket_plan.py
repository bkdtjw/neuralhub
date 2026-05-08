from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend.common.errors import AgentError
from backend.common.types import Message
from backend.core.s01_agent_loop import (
    ExecutionPlan,
    PlanExecuteRunner,
    SilentPlanRenderer,
    TodoState,
)
from backend.core.s05_skills import AgentRuntime, SpecRegistry
from backend.core.task_queue import TaskQueue
from backend.storage import SessionStore

from .websocket_support import LoopSettings, event_to_ws_message, serialize_message_for_client


class WsPlanRenderer(SilentPlanRenderer):
    """Renderer that forwards Plan & Execute lifecycle events over WebSocket."""

    def __init__(self, send_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        super().__init__()
        self._send = send_message

    async def _send_safe(self, message: dict[str, Any]) -> None:
        try:
            await self._send(message)
        except Exception:
            return

    async def on_recon_start(self, goal: str) -> None:
        await super().on_recon_start(goal)
        await self._send_safe({"type": "plan_recon_start", "goal": goal})

    async def on_recon_done(self, report_preview: str) -> None:
        await super().on_recon_done(report_preview)
        await self._send_safe({"type": "plan_recon_done", "report_preview": report_preview})

    async def on_plan_created(self, plan: ExecutionPlan, plan_name: str) -> None:
        await super().on_plan_created(plan, plan_name)
        steps = [
            {"step_id": step.step_id, "title": step.title, "description": step.description}
            for step in plan.steps
        ]
        await self._send_safe(
            {"type": "plan_created", "plan_name": plan_name, "goal": plan.goal, "steps": steps}
        )

    async def on_plan_approved(self, plan_name: str) -> None:
        await super().on_plan_approved(plan_name)
        await self._send_safe({"type": "plan_approved", "plan_name": plan_name})

    async def on_step_start(self, step_id: int, title: str, total_steps: int) -> None:
        await super().on_step_start(step_id, title, total_steps)
        await self._send_safe(
            {
                "type": "plan_step_update",
                "step_id": step_id,
                "status": "running",
                "title": title,
                "total_steps": total_steps,
            }
        )

    async def on_step_done(
        self, step_id: int, title: str, duration_s: float, output_summary: str
    ) -> None:
        await super().on_step_done(step_id, title, duration_s, output_summary)
        await self._send_safe(
            {
                "type": "plan_step_update",
                "step_id": step_id,
                "status": "done",
                "title": title,
                "duration_s": round(duration_s, 1),
                "output_summary": output_summary[:200],
            }
        )

    async def on_step_failed(self, step_id: int, title: str, error: str) -> None:
        await super().on_step_failed(step_id, title, error)
        await self._send_safe(
            {
                "type": "plan_step_update",
                "step_id": step_id,
                "status": "failed",
                "title": title,
                "error": error[:200],
            }
        )

    async def on_amendment(
        self, plan_name: str, version: int, reason: str, amended_step_count: int
    ) -> None:
        await super().on_amendment(plan_name, version, reason, amended_step_count)
        await self._send_safe(
            {
                "type": "plan_amendment",
                "plan_name": plan_name,
                "version": version,
                "reason": reason[:200],
            }
        )

    async def on_steps_updated(
        self,
        plan_name: str,
        steps: list[dict],
        todo_steps: list[dict],
    ) -> None:
        await super().on_steps_updated(plan_name, steps, todo_steps)
        await self._send_safe(
            {
                "type": "plan_steps_updated",
                "plan_name": plan_name,
                "steps": steps,
                "todo_steps": todo_steps,
            }
        )

    async def on_plan_completed(self, plan_name: str, todo_state: TodoState) -> None:
        await super().on_plan_completed(plan_name, todo_state)
        await self._send_safe({"type": "plan_completed", "plan_name": plan_name})

    async def on_plan_partial_failed(
        self,
        plan_name: str,
        todo_state: TodoState,
        done: int,
        failed: int,
    ) -> None:
        await super().on_plan_partial_failed(plan_name, todo_state, done, failed)
        await self._send_safe(
            {
                "type": "plan_partial_failed",
                "plan_name": plan_name,
                "done": done,
                "failed": failed,
            }
        )

    async def on_plan_cancelled(self, plan_name: str, todo_state: TodoState) -> None:
        await super().on_plan_cancelled(plan_name, todo_state)
        await self._send_safe({"type": "plan_cancelled", "plan_name": plan_name})


async def create_plan_runner(
    settings: LoopSettings,
    session_id: str,
    send_message: Callable[[dict[str, Any]], Awaitable[None]],
    store: SessionStore | None,
    agent_runtime: AgentRuntime | None,
    spec_registry: SpecRegistry | None,
    task_queue: TaskQueue | None,
) -> PlanExecuteRunner:
    try:
        _ = store, spec_registry
        if agent_runtime is None:
            raise AgentError("WS_AGENT_RUNTIME_MISSING", "agent runtime is not available")
        runner = await agent_runtime.create_runner(
            spec_id=settings.spec_id,
            mode="plan_execute",
            workspace=settings.workspace,
            session_id=session_id,
            model=settings.model,
            provider=settings.provider_id,
            renderer=WsPlanRenderer(send_message),
            task_queue=task_queue,
            event_handler=lambda event: send_message(event_to_ws_message(event)),
        )
        if not isinstance(runner, PlanExecuteRunner):
            raise AgentError(
                "WS_PLAN_RUNNER_TYPE_ERROR", "plan mode did not create PlanExecuteRunner"
            )
        return runner
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AgentError("WS_CREATE_PLAN_RUNNER_ERROR", str(exc)) from exc


async def run_plan_loop(
    runner: PlanExecuteRunner,
    message: str,
    send_message: Callable[[dict[str, Any]], Awaitable[None]],
    session_id: str,
    store: SessionStore | None,
) -> None:
    summary: Message | None = None
    try:
        await runner.run(message)
        summary = runner.build_exit_summary()
        await send_message({"type": "done", "message": serialize_message_for_client(summary)})
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await send_message({"type": "error", "message": str(exc)})
        except Exception:
            return
    finally:
        if store is not None:
            try:
                summary = summary or runner.build_exit_summary()
                await store.add_messages(
                    session_id, [Message(role="user", content=message), summary]
                )
            except Exception:
                pass


__all__ = ["WsPlanRenderer", "create_plan_runner", "run_plan_loop"]
