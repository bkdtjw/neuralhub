from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import websocket as websocket_route
from backend.api.routes.websocket import ConnectionManager
from backend.api.routes.websocket_plan import WsPlanRenderer, run_plan_loop
from backend.common.types import AgentConfig, Message
from backend.core.s01_agent_loop import AgentLoop, ExecutionPlan, PlanStep
from backend.core.s02_tools import ToolRegistry
from backend.tests.unit.plan_execute_test_support import MockAdapter


class MemoryStore:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def add_messages(self, session_id: str, messages: list[Message]) -> None:
        self.messages.extend(messages)

    async def get_messages(self, session_id: str) -> list[Message]:
        return list(self.messages)


class FakeRunner:
    def __init__(self) -> None:
        self.cancelled = False
        self.plan_name = "test-plan"

    async def run(self, message: str) -> Message:
        return self.build_exit_summary()

    def cancel(self) -> None:
        self.cancelled = True

    def build_exit_summary(self) -> Message:
        return Message(role="assistant", content=f"Plan: {self.plan_name}\nStatus: completed")


@pytest.mark.asyncio
async def test_ws_plan_renderer_sends_events() -> None:
    sent: list[dict[str, Any]] = []

    async def mock_send(message: dict[str, Any]) -> None:
        sent.append(message)

    renderer = WsPlanRenderer(mock_send)
    plan = ExecutionPlan(
        goal="test",
        steps=[PlanStep(step_id=1, title="step1", description="d1")],
    )
    await renderer.on_plan_created(plan, "test-plan")
    await renderer.on_step_start(1, "step1", 3)
    await renderer.on_step_done(1, "step1", 3.2, "summary")

    assert any(message["type"] == "plan_created" for message in sent)
    assert any(
        message["type"] == "plan_step_update" and message["status"] == "running" for message in sent
    )
    assert any(
        message["type"] == "plan_step_update" and message["status"] == "done" for message in sent
    )


@pytest.mark.asyncio
async def test_exit_summary_injected_to_session() -> None:
    sent: list[dict[str, Any]] = []

    async def mock_send(message: dict[str, Any]) -> None:
        sent.append(message)

    store = MemoryStore()
    runner = FakeRunner()
    await run_plan_loop(runner, "build plan", mock_send, "session-1", store)  # type: ignore[arg-type]

    messages = await store.get_messages("session-1")
    assert [message.role for message in messages] == ["user", "assistant"]
    assert "test-plan" in messages[1].content
    assert any(message["type"] == "done" for message in sent)


@pytest.mark.asyncio
async def test_disconnect_cleans_plan_runner() -> None:
    manager = ConnectionManager()
    runner = FakeRunner()
    manager._plan_runners["session-1"] = runner  # noqa: SLF001

    await manager.disconnect("session-1")

    assert "session-1" not in manager._plan_runners  # noqa: SLF001
    assert runner.cancelled is True


def test_plan_cancel_message_cancels_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    manager = ConnectionManager()

    async def fake_create_plan_runner(*_args: object) -> FakeRunner:
        return runner

    async def fake_run_plan_loop(*_args: object) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    _patch_websocket_runtime(monkeypatch, manager, fake_create_plan_runner, fake_run_plan_loop)
    app = FastAPI()
    app.include_router(websocket_route.router)

    with TestClient(app) as client, client.websocket_connect("/ws/session-1") as websocket:
        websocket.send_json(
            {
                "type": "run",
                "mode": "plan_execute",
                "model": "test",
                "provider_id": "fake",
                "message": "go",
            }
        )
        websocket.send_json({"type": "plan_cancel"})
        assert websocket.receive_json() == {"type": "status", "status": "idle"}

    assert runner.cancelled is True


def test_direct_mode_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ConnectionManager()
    created: dict[str, bool] = {}

    async def fake_create_loop(_payload: object) -> AgentLoop:
        created["loop"] = True
        return AgentLoop(
            config=AgentConfig(model="test"),
            adapter=MockAdapter(["done"]),
            tool_registry=ToolRegistry(),
        )

    async def fake_run_loop(payload: Any) -> None:
        await payload.send_message({"type": "done", "message": None})

    _patch_websocket_runtime(monkeypatch, manager, fake_create_loop, fake_run_loop)
    app = FastAPI()
    app.include_router(websocket_route.router)

    with TestClient(app) as client, client.websocket_connect("/ws/session-2") as websocket:
        websocket.send_json(
            {
                "type": "run",
                "mode": "direct",
                "model": "test",
                "provider_id": "fake",
                "message": "go",
            }
        )
        assert websocket.receive_json() == {"type": "done", "message": None}

    assert created["loop"] is True
    assert manager._plan_runners == {}  # noqa: SLF001


def _patch_websocket_runtime(
    monkeypatch: pytest.MonkeyPatch,
    manager: ConnectionManager,
    create_fn: Any,
    run_fn: Any,
) -> None:
    async def fake_forward(*_args: object) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    async def fake_publish(*_args: object) -> None:
        return None

    monkeypatch.setattr(websocket_route, "manager", manager)
    monkeypatch.setattr(websocket_route, "create_plan_runner", create_fn)
    monkeypatch.setattr(websocket_route, "create_loop", create_fn)
    monkeypatch.setattr(websocket_route, "run_plan_loop", run_fn)
    monkeypatch.setattr(websocket_route, "run_loop", run_fn)
    monkeypatch.setattr(websocket_route, "forward_session_messages", fake_forward)
    monkeypatch.setattr(websocket_route, "publish_session_message", fake_publish)
