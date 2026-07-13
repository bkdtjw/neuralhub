from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.common.logging import get_logger
from backend.api.routes.providers import provider_manager
from backend.common.errors import AgentError
from backend.common.types import Message
from backend.core.s01_agent_loop import AgentLoop, PlanCheckpointStore, PlanExecuteRunner, PlanState
from backend.core.s01_agent_loop.plan_state_machine import TERMINAL_PHASES
from backend.storage import SessionStore

from .websocket_knowledge import prepare_knowledge_run
from .websocket_loop_cache import LoopCache
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
    serialize_message_for_client,
)

router = APIRouter()
logger = get_logger(component="websocket_route")


class ConnectionManager:
    def __init__(self) -> None:
        # 多客户端模型（feat/event-hooks）：一个会话可被多个 WebSocket 同时订阅。
        self._connections: dict[str, set[WebSocket]] = {}
        self._plan_runners: dict[str, PlanExecuteRunner] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._subscriber_tasks: dict[str, dict[WebSocket, asyncio.Task[Any]]] = {}
        # LoopCache 组合进来做 LRU 封顶，兜底防止断连后 loop 常驻内存 OOM。
        self._loop_cache = LoopCache(self._is_busy)

    @property
    def _loops(self) -> OrderedDict[str, AgentLoop]:
        return self._loop_cache.loops

    @property
    def _loop_settings(self) -> dict[str, LoopSettings]:
        return self._loop_cache.settings

    def _is_busy(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        return task is not None and not task.done()

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        try:
            self._connections.setdefault(session_id, set()).add(ws)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_CONNECT_ERROR", str(exc)) from exc

    async def disconnect(
        self,
        session_id: str,
        *,
        websocket: WebSocket | None = None,
        subscriber_task: asyncio.Task[Any] | None = None,
        store: SessionStore | None = None,
    ) -> None:
        # 先做纯同步、不可失败的清理，确保订阅任务与连接引用一定被释放（多客户端：按 ws 精确摘除）。
        self._remove_subscriber_task(session_id, websocket, subscriber_task)
        if websocket is None:
            self._connections.pop(session_id, None)
        else:
            sockets = self._connections.get(session_id)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    self._connections.pop(session_id, None)
        # 消息落盘可能失败，但不应阻断上面的清理；失败仅记录日志，不再抛异常。
        loop = self._loops.get(session_id)
        if loop is not None:
            try:
                await self._sync_messages(session_id, loop, store)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ws_disconnect_sync_messages_failed", session_id=session_id, error=str(exc)
                )
            # 无在跑任务且已无其他客户端连接时回收 loop（落库已在上方完成），避免断连后 loop 常驻内存。
            # 有任务在跑或仍有客户端订阅则保留：交由其 done_callback / 后续断连回收。
            if self._connections.get(session_id) is None and not self._is_busy(session_id):
                loop.abort()
                self._loop_cache.pop(session_id)

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
            subscriber_tasks = self._subscriber_tasks.pop(session_id, {})
            for subscriber_task in subscriber_tasks.values():
                if not subscriber_task.done():
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
            history = loop.message_history
            if history.has_checkpoint_fn and not history.checkpoint_failed:
                return
            await store.save_messages(session_id, loop.messages)
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_SYNC_MESSAGES_ERROR", str(exc)) from exc

    def get_loop(self, session_id: str) -> AgentLoop | None:
        return self._loop_cache.get(session_id)

    def get_loop_settings(self, session_id: str) -> LoopSettings | None:
        return self._loop_cache.get_settings(session_id)

    async def store_loop(
        self,
        session_id: str,
        loop: AgentLoop,
        settings: LoopSettings,
        store: SessionStore | None = None,
    ) -> None:
        # 存入 loop 并封顶缓存；被 LRU 淘汰的空闲 loop 先尽力落库再 abort，防止内存无界增长。
        for victim_id, victim in self._loop_cache.store(session_id, loop, settings):
            try:
                await self._sync_messages(victim_id, victim, store)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws_loop_evict_sync_failed", session_id=victim_id, error=str(exc))
            victim.abort()

    def _evict_if_idle(self, session_id: str) -> None:
        # 供 done_callback 的同步上下文调用：连接已断且无在跑任务时回收 loop。
        # 消息已由 run_loop 的 finally 落库，这里只 abort + pop，不在同步回调里 await。
        if self._connections.get(session_id) is not None:
            return
        if self._is_busy(session_id):
            return
        loop = self._loop_cache.pop(session_id)
        if loop is not None:
            loop.abort()

    def set_subscriber_task(
        self, session_id: str, websocket: WebSocket, task: asyncio.Task[Any]
    ) -> None:
        tasks = self._subscriber_tasks.setdefault(session_id, {})
        existing = tasks.get(websocket)
        if existing and not existing.done():
            existing.cancel()
        tasks[websocket] = task

    async def broadcast(self, session_id: str, payload: dict[str, Any]) -> None:
        try:
            sockets = list(self._connections.get(session_id, set()))
            failed: list[WebSocket] = []
            for ws in sockets:
                try:
                    await ws.send_json(payload)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ws_send_failed", session_id=session_id, error=str(exc))
                    failed.append(ws)
            if failed:
                active = self._connections.get(session_id)
                if active is not None:
                    for ws in failed:
                        active.discard(ws)
                        self._remove_subscriber_task(session_id, ws, None)
                    if not active:
                        self._connections.pop(session_id, None)
            # 跨 worker 扇出是尽力而为：publish 失败（如 Redis 池耗尽）只大声告警，
            # 本地已 send 的帧不受影响，也不炸上游 fire-and-forget 事件任务。
            try:
                await publish_session_message(session_id, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ws_cross_worker_publish_degraded", session_id=session_id, error=str(exc)
                )
        except Exception as exc:  # noqa: BLE001
            raise AgentError("WS_BROADCAST_ERROR", str(exc)) from exc

    def _remove_subscriber_task(
        self,
        session_id: str,
        websocket: WebSocket | None,
        subscriber_task: asyncio.Task[Any] | None,
    ) -> None:
        tasks = self._subscriber_tasks.get(session_id)
        if not tasks:
            pending: list[asyncio.Task[Any]] = [subscriber_task] if subscriber_task else []
        elif websocket is None and subscriber_task is None:
            pending = list(tasks.values())
            self._subscriber_tasks.pop(session_id, None)
        elif websocket is not None:
            task = tasks.pop(websocket, None) or subscriber_task
            pending = [task] if task else []
            if not tasks:
                self._subscriber_tasks.pop(session_id, None)
        else:
            pending = []
            for ws, task in list(tasks.items()):
                if task is subscriber_task:
                    tasks.pop(ws, None)
                    pending.append(task)
            if not tasks:
                self._subscriber_tasks.pop(session_id, None)
        for task in pending:
            if not task.done():
                task.cancel()


manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    store = get_store(websocket)
    await manager.connect(session_id, websocket)
    logger.info("ws_connected", session_id=session_id)
    await _send_resume_available(websocket, session_id)
    subscriber_task = asyncio.create_task(forward_session_messages(session_id, websocket))
    manager.set_subscriber_task(session_id, websocket, subscriber_task)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "run":
                # 忙判定以任务存活为准：旧的状态集合会漏掉 compacting/waiting_approval，
                # 从而在这些阶段放行第二个 run，造成同一 loop 并发。task 未结束即拒绝，
                # 拒绝并发后下方 manager._tasks[session_id] = task 也不会再覆盖存活句柄。
                task = manager._tasks.get(session_id)
                if task and not task.done():
                    await websocket.send_json({"type": "error", "message": "Agent is busy"})
                    continue
                loop = manager.get_loop(session_id)
                settings = await resolve_loop_settings(parse_loop_settings(data), provider_manager)
                state = websocket.app.state
                user_message = str(data.get("message", "")).strip()
                logger.info(
                    "ws_run_received",
                    session_id=session_id,
                    message_length=len(user_message),
                    model=settings.model,
                    provider_id=settings.provider_id,
                    mode=settings.mode,
                )

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
                        await websocket.send_json(
                            {"type": "error", "message": "message is required"}
                        )
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
                knowledge_run = await prepare_knowledge_run(settings, user_message)
                if knowledge_run.empty_reply:
                    answer = Message(role="assistant", content=knowledge_run.empty_reply)
                    if store is not None:
                        await store.add_messages(
                            session_id,
                            [Message(role="user", content=user_message), answer],
                        )
                    await send_message({"type": "message", "content": answer.content})
                    await send_message(
                        {"type": "done", "message": serialize_message_for_client(answer)}
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
                    await manager.store_loop(session_id, loop, settings, store)
                bridge = loop.bridge
                if bridge is not None and bridge.needs_sync():
                    await bridge.sync_if_needed()
                task = asyncio.create_task(
                    run_loop(
                        RunLoopInput(
                            loop=loop,
                            message=knowledge_run.message,
                            display_message=knowledge_run.display_message,
                            send_message=send_message,
                            session_id=session_id,
                            store=store,
                        )
                    )
                )
                task.add_done_callback(
                    lambda _: (
                        manager._tasks.pop(session_id, None),
                        manager._evict_if_idle(session_id),
                    )
                )
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
                    await websocket.send_json(
                        {"type": "error", "message": "Plan is already running"}
                    )
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
                        manager._evict_if_idle(session_id),
                    )
                )
                manager._tasks[session_id] = task
            elif msg_type == "plan_discard":
                checkpoint_store = PlanCheckpointStore()
                state = await asyncio.to_thread(
                    _latest_incomplete_checkpoint, checkpoint_store, session_id, session_id
                )
                if state is not None:
                    checkpoint_store.delete(state.session_id, state.plan_name)
                await manager.broadcast(session_id, {"type": "status", "status": "idle"})
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
                await manager.broadcast(session_id, {"type": "status", "status": "idle"})
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
                await manager.broadcast(session_id, {"type": "status", "status": "idle"})
            else:
                await websocket.send_json({"type": "error", "message": "Unsupported message type"})
    except WebSocketDisconnect:
        # 保留断连日志（可观测性）；清理统一交给 finally，避免在此重复 disconnect。
        logger.info("ws_disconnected", session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        # 尽力通知客户端；发送失败也无妨，清理仍由 finally 兜底，不再 return 短路。
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await manager.disconnect(
            session_id,
            websocket=websocket,
            subscriber_task=subscriber_task,
            store=store,
        )


async def _send_resume_available(websocket: WebSocket, session_id: str) -> None:
    store = PlanCheckpointStore()
    # 顺带低频清理超龄非终态 checkpoint（放线程避免阻塞事件循环）；GC 尽力而为，
    # 失败也绝不能拖垮连接与恢复提示，故吞掉异常仅记日志。
    try:
        await asyncio.to_thread(store.cleanup_stale)
    except Exception:  # noqa: BLE001
        logger.warning("plan_checkpoint_cleanup_stale_failed", session_id=session_id)
    state = await asyncio.to_thread(
        _latest_incomplete_checkpoint, store, session_id, session_id
    )
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
