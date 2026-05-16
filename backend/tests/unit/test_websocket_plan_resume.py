from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import websocket as websocket_route
from backend.api.routes.websocket import ConnectionManager
from backend.api.routes.websocket_plan import run_plan_resume_loop
from backend.common.types import Message
from backend.core.s01_agent_loop import PlanPhase, PlanState


class FakeRunner:
    def __init__(self) -> None:
        self.plan_name = "test-plan"
        self.cancelled = False

    async def resume_run(self) -> Message:
        return self.build_exit_summary()

    def cancel(self) -> None:
        self.cancelled = True

    def build_exit_summary(self) -> Message:
        return Message(role="assistant", content=f"Plan: {self.plan_name}")


class MemoryStore:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def add_messages(self, session_id: str, messages: list[Message]) -> None:
        self.messages.extend(messages)


@pytest.mark.asyncio
async def test_run_plan_resume_loop_stores_only_summary() -> None:
    sent: list[dict[str, object]] = []
    store = MemoryStore()

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await run_plan_resume_loop(FakeRunner(), send, "session-1", store)  # type: ignore[arg-type]

    assert [message.role for message in store.messages] == ["assistant"]
    assert sent and sent[0]["type"] == "done"


def test_plan_resume_message_starts_resume_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    manager = ConnectionManager()
    state = PlanState(
        plan_name="resume-plan",
        session_id="session-1",
        phase=PlanPhase.EXECUTING,
        current_step_id=3,
    )

    class FakeCheckpointStore:
        def find_incomplete_by_owner(self, owner_id: str) -> list[PlanState]:
            return [state]

    async def fake_create_resume_runner(*_args: object) -> FakeRunner:
        return runner

    async def fake_run_plan_resume_loop(
        resumed: FakeRunner,
        send_message: object,
        *_args: object,
    ) -> None:
        assert resumed is runner
        await send_message({"type": "done", "message": None})  # type: ignore[misc]

    _patch_resume_runtime(monkeypatch, manager)
    monkeypatch.setattr(websocket_route, "PlanCheckpointStore", FakeCheckpointStore)
    monkeypatch.setattr(websocket_route, "create_plan_resume_runner", fake_create_resume_runner)
    monkeypatch.setattr(websocket_route, "run_plan_resume_loop", fake_run_plan_resume_loop)
    app = FastAPI()
    app.include_router(websocket_route.router)

    with TestClient(app) as client, client.websocket_connect("/ws/session-1") as websocket:
        assert websocket.receive_json() == {
            "type": "plan_resume_available",
            "plan_name": "resume-plan",
            "phase": "executing",
            "interrupted_step_id": 3,
        }
        websocket.send_json({"type": "plan_resume", "model": "test"})
        assert websocket.receive_json() == {"type": "done", "message": None}


def test_completed_checkpoint_does_not_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    manager = ConnectionManager()

    class FakeCheckpointStore:
        def find_incomplete_by_owner(self, owner_id: str) -> list[PlanState]:
            return []

    async def fake_create_plan_runner(*_args: object) -> FakeRunner:
        return runner

    async def fake_create_resume_runner(*_args: object) -> None:
        raise AssertionError("resume should not be called")

    async def fake_run_plan_loop(*_args: object) -> None:
        return None

    _patch_resume_runtime(monkeypatch, manager)
    monkeypatch.setattr(websocket_route, "PlanCheckpointStore", FakeCheckpointStore)
    monkeypatch.setattr(websocket_route, "create_plan_runner", fake_create_plan_runner)
    monkeypatch.setattr(websocket_route, "create_plan_resume_runner", fake_create_resume_runner)
    monkeypatch.setattr(websocket_route, "run_plan_loop", fake_run_plan_loop)
    app = FastAPI()
    app.include_router(websocket_route.router)

    with TestClient(app) as client, client.websocket_connect("/ws/session-1") as websocket:
        websocket.send_json(
            {
                "type": "run",
                "mode": "plan_execute",
                "model": "test",
                "message": "new",
            }
        )

    assert manager._plan_runners == {}  # noqa: SLF001


def _patch_resume_runtime(monkeypatch: pytest.MonkeyPatch, manager: ConnectionManager) -> None:
    async def fake_resolve(settings: object, *_args: object) -> object:
        return settings

    async def fake_forward(*_args: object) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    async def fake_publish(*_args: object) -> None:
        return None

    monkeypatch.setattr(websocket_route, "manager", manager)
    monkeypatch.setattr(websocket_route, "resolve_loop_settings", fake_resolve)
    monkeypatch.setattr(websocket_route, "forward_session_messages", fake_forward)
    monkeypatch.setattr(websocket_route, "publish_session_message", fake_publish)
