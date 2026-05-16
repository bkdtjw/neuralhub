from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api.routes.providers import provider_manager
from backend.common.errors import AgentError
from backend.core.s01_agent_loop import AgentLoop, PlanCheckpointStore, PlanExecuteRunner, PlanState
from backend.core.s01_agent_loop.plan_state_machine import TERMINAL_PHASES
from backend.storage import SessionStore

from .websocket_plan import create_plan_runner, run_plan_loop, run_plan_resume_loop
from .websocket_plan_resume import create_plan_resume_runner
from .websocket_pubsub import forward_session_messages, publish_session_message
from .websocket_runtime import CreateLoopInput, create_loop
from .websocket_support import (
    LoopSettings,
    RunLoopInput,
    get_store,
    parse_loop_settings,
    resolve_loop_settings,
    run_loop,
)

router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._loops: dict[str, AgentLoop] = {}
        self._plan_runners: dict[str, PlanExecuteRunner] = {}
        self._loop_settings: dict[str, LoopSettings] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._subscriber_tasks: dict[str, asyncio.Task[Any]] = {}

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        try:
            self._connections[session_id] = ws
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_CONNECT_ERROR", str(exc)) from exc

    async def disconnect(self, session_id: str, store: SessionStore | None = None) -> None:
        try:
            loop = self._loops.pop(session_id, None)
            if loop is not None:
                await self._sync_messages(session_id, loop, store)
                loop.abort()
            self._plan_runners.pop(session_id, None)
            self._loop_settings.pop(session_id, None)
            task = self._tasks.pop(session_id, None)
            if task and not task.done():
                task.cancel()
            subscriber_task = self._subscriber_tasks.pop(session_id, None)
            if subscriber_task and not subscriber_task.done():
                subscriber_task.cancel()
            self._connections.pop(session_id, None)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_DISCONNECT_ERROR", str(exc)) from exc

    async def clear_session(self, session_id: str, store: SessionStore | None = None) -> None:
        try:
            loop = self._loops.pop(session_id, None)
            if loop is not None:
                await self._sync_messages(session_id, loop, store)
                loop.abort()
            runner = self._plan_runners.pop(session_id, None)
            if runner is not None:
                runner.cancel()
            self._loop_settings.pop(session_id, None)
            task = self._tasks.pop(session_id, None)
            if task and not task.done():
                task.cancel()
            subscriber_task = self._subscriber_tasks.pop(session_id, None)
            if subscriber_task and not subscriber_task.done():
                subscriber_task.cancel()
            self._connections.pop(session_id, None)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_CLEAR_SESSION_ERROR", str(exc)) from exc

    async def _sync_messages(
        self, session_id: str, loop: AgentLoop, store: SessionStore | None
    ) -> None:
        try:
            if store is None:
                return
            await store.save_messages(session_id, loop.messages)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_SYNC_MESSAGES_ERROR", str(exc)) from exc

    def get_loop(self, session_id: str) -> AgentLoop | None:
        return self._loops.get(session_id)

    def get_loop_settings(self, session_id: str) -> LoopSettings | None:
        return self._loop_settings.get(session_id)

    def set_subscriber_task(self, session_id: str, task: asyncio.Task[Any]) -> None:
        existing = self._subscriber_tasks.get(session_id)
        if existing and not existing.done():
            existing.cancel()
        self._subscriber_tasks[session_id] = task

    async def broadcast(self, session_id: str, payload: dict[str, Any]) -> None:
        try:
            ws = self._connections.get(session_id)
            if ws is not None:
                try:
                    await ws.send_json(payload)
                except Exception:
                    self._connections.pop(session_id, None)
            await publish_session_message(session_id, payload)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_BROADCAST_ERROR", str(exc)) from exc


manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    store = get_store(websocket)
    await manager.connect(session_id, websocket)
    await _send_resume_available(websocket, session_id)
    manager.set_subscriber_task(
        session_id,
        asyncio.create_task(forward_session_messages(session_id, websocket)),
    )
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "run":
                loop = manager.get_loop(session_id)
                task = manager._tasks.get(session_id)
                if (
                    loop
                    and loop.status in {"thinking", "tool_calling"}
                    and task
                    and not task.done()
                ):
                    await websocket.send_json({"type": "error", "message": "Agent is busy"})
                    continue
                settings = await resolve_loop_settings(parse_loop_settings(data), provider_manager)
                state = websocket.app.state
                user_message = str(data.get("message", "")).strip()

                async def send_message(message: dict[str, Any]) -> None:
                    await manager.broadcast(session_id, message)

                if settings.mode == "plan_execute":
                    if manager._plan_runners.get(session_id):
                        await websocket.send_json(
                            {"type": "error", "message": "Plan is already running"}
                        )
                        continue
                    checkpoint_store = PlanCheckpointStore()
                    existing_state = _latest_incomplete_checkpoint(
                        checkpoint_store, session_id, session_id
                    )
                    if existing_state is not None:
                        await send_message(
                            {
                                "type": "plan_resume_available",
                                "plan_name": existing_state.plan_name,
                                "phase": existing_state.phase.value,
                                "interrupted_step_id": _interrupted_step_id(existing_state),
                            }
                        )
                        continue
                    if not user_message and not settings.spec_id:
                        await websocket.send_json({"type": "error", "message": "message is required"})
                        continue
                    try:
                        runner = await create_plan_runner(
                            settings,
                            session_id,
                            send_message,
                            store,
                            getattr(state, "agent_runtime", None),
                            getattr(state, "spec_registry", None),
                            getattr(state, "task_queue", None),
                        )
                    except Exception as exc:  # noqa: BLE001
                        await websocket.send_json({"type": "error", "message": str(exc)})
                        continue
                    manager._plan_runners[session_id] = runner
                    task = asyncio.create_task(
                        run_plan_loop(runner, user_message, send_message, session_id, store)
                    )
                    task.add_done_callback(
                        lambda _: (
                            manager._plan_runners.pop(session_id, None),
                            manager._tasks.pop(session_id, None),
                        )
                    )
                    manager._tasks[session_id] = task
                    continue
                if not user_message and not settings.spec_id:
                    await websocket.send_json({"type": "error", "message": "message is required"})
                    continue
                if manager._plan_runners.get(session_id):
                    await websocket.send_json(
                        {"type": "error", "message": "Plan is already running"}
                    )
                    continue
                current_settings = manager.get_loop_settings(session_id)
                if (
                    loop is None
                    or current_settings is None
                    or current_settings.model_dump() != settings.model_dump()
                ):
                    if loop is not None:
                        await manager._sync_messages(session_id, loop, store)  # noqa: SLF001
                        loop.abort()
                    loop = await create_loop(
                        CreateLoopInput(
                            session_id=session_id,
                            settings=settings,
                            store=store,
                            previous_loop=loop,
                            previous_settings=current_settings,
                            agent_runtime=getattr(state, "agent_runtime", None),
                            spec_registry=getattr(state, "spec_registry", None),
                            task_queue=getattr(state, "task_queue", None),
                            event_sender=send_message,
                        )
                    )
                    manager._loops[session_id] = loop
                    manager._loop_settings[session_id] = settings
                bridge = loop.bridge
                if bridge is not None and bridge.needs_sync():
                    await bridge.sync_if_needed()
                task = asyncio.create_task(
                    run_loop(
                        RunLoopInput(
                            loop=loop,
                            message=user_message,
                            send_message=send_message,
                            session_id=session_id,
                            store=store,
                        )
                    )
                )
                task.add_done_callback(lambda _: manager._tasks.pop(session_id, None))
                manager._tasks[session_id] = task
            elif msg_type == "plan_approve":
                runner = manager._plan_runners.get(session_id)
                if runner is None:
                    await websocket.send_json({"type": "error", "message": "No plan to approve"})
                    continue
                runner.approve()
            elif msg_type == "plan_reject":
                runner = manager._plan_runners.get(session_id)
                if runner is None:
                    await websocket.send_json({"type": "error", "message": "No plan to reject"})
                    continue
                reason = str(data.get("reason", "")).strip()
                runner.reject(reason)
            elif msg_type == "plan_resume":
                if manager._plan_runners.get(session_id):
                    await websocket.send_json({"type": "error", "message": "Plan is already running"})
                    continue
                settings = await resolve_loop_settings(parse_loop_settings(data), provider_manager)
                state = websocket.app.state

                async def send_message(message: dict[str, Any]) -> None:
                    await manager.broadcast(session_id, message)

                try:
                    runner = await create_plan_resume_runner(
                        settings,
                        session_id,
                        send_message,
                        store,
                        getattr(state, "agent_runtime", None),
                        getattr(state, "spec_registry", None),
                        getattr(state, "task_queue", None),
                        PlanCheckpointStore(),
                    )
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                if runner is None:
                    await websocket.send_json({"type": "error", "message": "No plan to resume"})
                    continue
                manager._plan_runners[session_id] = runner
                task = asyncio.create_task(
                    run_plan_resume_loop(runner, send_message, session_id, store)
                )
                task.add_done_callback(
                    lambda _: (
                        manager._plan_runners.pop(session_id, None),
                        manager._tasks.pop(session_id, None),
                    )
                )
                manager._tasks[session_id] = task
            elif msg_type == "plan_discard":
                state = _latest_incomplete_checkpoint(PlanCheckpointStore(), session_id, session_id)
                if state is not None:
                    PlanCheckpointStore().delete(state.session_id, state.plan_name)
                await websocket.send_json({"type": "status", "status": "idle"})
            elif msg_type in {"tool_approve", "tool_reject"}:
                tool_call_id = str(data.get("tool_call_id", "")).strip()
                approved = msg_type == "tool_approve"
                handled = _resolve_tool_approval(session_id, tool_call_id, approved)
                if not handled:
                    await websocket.send_json(
                        {"type": "error", "message": "No pending tool approval"}
                    )
            elif msg_type == "plan_cancel":
                runner = manager._plan_runners.get(session_id)
                if runner is not None:
                    runner.cancel()
                await websocket.send_json({"type": "status", "status": "idle"})
            elif msg_type == "abort":
                loop = manager.get_loop(session_id)
                if loop:
                    loop.abort()
                runner = manager._plan_runners.pop(session_id, None)
                if runner is not None:
                    runner.cancel()
                task = manager._tasks.get(session_id)
                if task and not task.done():
                    task.cancel()
                await websocket.send_json({"type": "status", "status": "idle"})
            else:
                await websocket.send_json({"type": "error", "message": "Unsupported message type"})
    except WebSocketDisconnect:
        await manager.disconnect(session_id, store)
    except Exception as exc:  # noqa: BLE001
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            return
        await manager.disconnect(session_id, store)


async def _send_resume_available(websocket: WebSocket, session_id: str) -> None:
    state = _latest_incomplete_checkpoint(PlanCheckpointStore(), session_id, session_id)
    if state is None:
        return
    await websocket.send_json(
        {
            "type": "plan_resume_available",
            "plan_name": state.plan_name,
            "phase": state.phase.value,
            "interrupted_step_id": _interrupted_step_id(state),
        }
    )


def _latest_incomplete_checkpoint(
    checkpoint_store: PlanCheckpointStore,
    session_id: str,
    owner_id: str,
) -> PlanState | None:
    states = [
        state
        for state in checkpoint_store.find_incomplete_by_owner(owner_id)
        if state.session_id == session_id and state.phase not in TERMINAL_PHASES
    ]
    if not states:
        return None
    return max(states, key=lambda state: state.updated_at)


def _resolve_tool_approval(session_id: str, tool_call_id: str, approved: bool) -> bool:
    if not tool_call_id:
        return False
    loop = manager.get_loop(session_id)
    if loop is not None:
        resolver = loop.approve_tool_call if approved else loop.reject_tool_call
        if resolver(tool_call_id):
            return True
    runner = manager._plan_runners.get(session_id)
    if runner is None:
        return False
    resolver = runner.approve_tool_call if approved else runner.reject_tool_call
    return resolver(tool_call_id)


def _interrupted_step_id(state: object) -> int:
    current = int(getattr(state, "current_step_id", 0) or 0)
    if current:
        return current
    todo = getattr(state, "todo", None)
    for step in getattr(todo, "steps", []) or []:
        if getattr(step, "status", "") in {"running", "pending"}:
            return int(getattr(step, "id", 0) or 0)
    return 0


__all__ = ["ConnectionManager", "manager", "router"]
